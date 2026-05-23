import json
import asyncio
import time
import logging
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from core.event_bus import EventBus, Event
from core.heartbeat import Heartbeat
from persona.state_manager import StateManager
from brain.core import Brain
from brain.tts import TTSManager
from memory.short_term import ShortTermMemory
from config.settings import settings
from memory.episodic_memory import EpisodicMemory
from memory.memory_process import Hippocampus
from memory.db_memory import DBMemory
from memory.entity_extraction import EntityExtractionMemory
from config.logging_config import get_logger
from tools.processor import ToolCallProcessor
from archive import ArchiveManager

# Configure logging
logger = get_logger(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_LIVE2D_DIR = os.path.join(BASE_DIR, "data", "user_live2d")
MAX_LIVE2D_ZIP_BYTES = 200 * 1024 * 1024
MAX_LIVE2D_EXTRACTED_BYTES = 500 * 1024 * 1024
DEFAULT_PROFILE_DISPLAY = {
    "scale": 1.0,
    "offset_x": 0,
    "offset_y": 0,
    "anchor": {"x": 0.5, "y": 0.5},
    "auto_fit": True,
}


class ConnectionManager:
    """Async connection manager"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Pure async broadcast"""
        if not self.active_connections:
            return

        payload = json.dumps(message, ensure_ascii=False)
        tasks = []
        for connection in self.active_connections:
            tasks.append(self._safe_send(connection, payload))
        await asyncio.gather(*tasks)

    async def _safe_send(self, websocket: WebSocket, payload: str):
        try:
            await websocket.send_text(payload)
        except Exception:
            self.disconnect(websocket)


class EmberServer:
    def __init__(self):
        self.app = FastAPI()
        self.event_bus = EventBus()
        self.manager = ConnectionManager()
        self.loop = None
        self.current_ai_msg_id = None  # Track ongoing AI message ID
        self.current_full_text = ""  # Track full text for TTS
        self._tts_semaphore = asyncio.Semaphore(3)  # 限制并发 TTS 数量为 3

        # Initialize components
        self.heartbeat = Heartbeat(self.event_bus, interval=settings.HEARTBEAT_INTERVAL)
        self.memory = ShortTermMemory(
            base_prompt=settings.SYSTEM_PROMPT,
            max_memory_size=settings.CONTEXT_WINDOW_SIZE,
        )
        self.episodic_memory = EpisodicMemory(self.event_bus)
        self.hippocampus = Hippocampus(self.event_bus)
        self.db_memory = DBMemory(self.event_bus)

        # 创建并复用 ToolCallProcessor
        self.tool_processor = ToolCallProcessor.create_with_memory_tool(
            self.hippocampus
        )

        self.state_manager = StateManager(
            self.event_bus, self.hippocampus, self.memory, self.tool_processor
        )
        self.entity_memory = EntityExtractionMemory(self.event_bus)
        self.brain = Brain(
            self.event_bus,
            self.state_manager,
            self.memory,
            self.hippocampus,
            self.tool_processor,
        )
        self.tts_manager = TTSManager(voice="zh-CN-XiaoxiaoNeural")

        # Initialize archive manager
        self.archive_manager = ArchiveManager(
            event_bus=self.event_bus,
            hippocampus=self.hippocampus,
            heartbeat=self.heartbeat,
            state_manager=self.state_manager,
            short_term_memory=self.memory,
            episodic_memory=self.episodic_memory,
            db_memory=self.db_memory,
        )

        self._setup_middleware()
        self._setup_routes()
        self._setup_event_handlers()

    def _normalize_profile_display(self, display: dict | None) -> dict:
        if not isinstance(display, dict):
            display = {}
        anchor = display.get("anchor")
        if not isinstance(anchor, dict):
            anchor = {}

        def number_or_default(value, default):
            return value if isinstance(value, (int, float)) else default

        def bool_or_default(value, default):
            return value if isinstance(value, bool) else default

        return {
            "scale": number_or_default(display.get("scale"), DEFAULT_PROFILE_DISPLAY["scale"]),
            "offset_x": number_or_default(display.get("offset_x"), DEFAULT_PROFILE_DISPLAY["offset_x"]),
            "offset_y": number_or_default(display.get("offset_y"), DEFAULT_PROFILE_DISPLAY["offset_y"]),
            "anchor": {
                "x": number_or_default(anchor.get("x"), DEFAULT_PROFILE_DISPLAY["anchor"]["x"]),
                "y": number_or_default(anchor.get("y"), DEFAULT_PROFILE_DISPLAY["anchor"]["y"]),
            },
            "auto_fit": bool_or_default(display.get("auto_fit"), DEFAULT_PROFILE_DISPLAY["auto_fit"]),
        }

    def _load_profiles_config(self) -> dict:
        profiles_path = os.path.join(BASE_DIR, "config", "profiles.json")
        try:
            with open(profiles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning("config/profiles.json not found; using fallback Live2D profile")
            return {
                "current_profile_id": "default",
                "profiles": [
                    {
                        "id": "default",
                        "name": "Default",
                        "model_path": settings.LIVE2D_MODEL_PATH,
                    }
                ],
            }
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse config/profiles.json: {e}")
            return {"current_profile_id": "", "profiles": []}

        if not isinstance(data.get("profiles"), list):
            data["profiles"] = []
        for profile in data["profiles"]:
            if isinstance(profile, dict):
                profile["display"] = self._normalize_profile_display(profile.get("display"))
        if "current_profile_id" not in data:
            data["current_profile_id"] = data["profiles"][0]["id"] if data["profiles"] else ""
        return data

    def _save_profiles_config(self, profiles_config: dict):
        profiles_path = os.path.join(BASE_DIR, "config", "profiles.json")
        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(profiles_config, f, ensure_ascii=False, indent=2)

    async def _save_limited_upload(self, upload: UploadFile, target_path: Path) -> int:
        total_size = 0
        with target_path.open("wb") as f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_LIVE2D_ZIP_BYTES:
                    raise HTTPException(status_code=413, detail="ZIP 文件不能超过 200MB")
                f.write(chunk)
        if total_size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        return total_size

    def _safe_zip_target(self, extract_root: Path, member_name: str) -> Path:
        normalized_name = member_name.replace("\\", "/")
        member_path = PurePosixPath(normalized_name)
        if (
            not normalized_name
            or "\x00" in normalized_name
            or member_path.is_absolute()
            or any(part in ("", ".", "..") for part in member_path.parts)
            or any(":" in part for part in member_path.parts)
        ):
            raise HTTPException(status_code=400, detail="ZIP 内包含不安全路径")

        root = extract_root.resolve()
        target = (root / Path(*member_path.parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=400, detail="ZIP 内包含路径逃逸")
        return target

    def _validate_and_extract_live2d_zip(self, zip_path: Path, extract_root: Path) -> list[Path]:
        if not zipfile.is_zipfile(zip_path):
            raise HTTPException(status_code=400, detail="上传文件不是有效的 ZIP")

        extract_root.mkdir(parents=True, exist_ok=False)
        total_declared_size = 0
        total_extracted_size = 0
        seen_targets: set[str] = set()

        try:
            with zipfile.ZipFile(zip_path) as zf:
                members = zf.infolist()
                if not members:
                    raise HTTPException(status_code=400, detail="ZIP 文件为空")

                safe_members: list[tuple[zipfile.ZipInfo, Path]] = []
                for info in members:
                    target = self._safe_zip_target(extract_root, info.filename)
                    target_key = os.path.normcase(str(target))
                    if target_key in seen_targets:
                        raise HTTPException(status_code=400, detail="ZIP 内包含重复路径")
                    seen_targets.add(target_key)

                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise HTTPException(status_code=400, detail="ZIP 内不允许包含符号链接")

                    total_declared_size += info.file_size
                    if total_declared_size > MAX_LIVE2D_EXTRACTED_BYTES:
                        raise HTTPException(status_code=413, detail="解压后文件总大小不能超过 500MB")
                    safe_members.append((info, target))

                file_target_keys = {
                    os.path.normcase(str(target))
                    for info, target in safe_members
                    if not info.is_dir()
                }
                root = extract_root.resolve()
                for info, target in safe_members:
                    if info.is_dir():
                        continue
                    for parent in target.parents:
                        if parent == root:
                            break
                        if os.path.normcase(str(parent)) in file_target_keys:
                            raise HTTPException(status_code=400, detail="ZIP 内包含冲突路径")

                for info, target in safe_members:
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue

                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as source, target.open("wb") as dest:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            total_extracted_size += len(chunk)
                            if total_extracted_size > MAX_LIVE2D_EXTRACTED_BYTES:
                                raise HTTPException(status_code=413, detail="解压后文件总大小不能超过 500MB")
                            dest.write(chunk)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="上传文件不是有效的 ZIP")

        return [
            path
            for path in extract_root.rglob("*")
            if path.is_file() and path.name.lower().endswith(".model3.json")
        ]

    def _build_uploaded_profile_name(self, upload: UploadFile, name: str | None) -> str:
        profile_name = (name or "").strip()
        if not profile_name:
            profile_name = Path(upload.filename or "Imported Live2D").stem.strip()
        return profile_name[:80] or "Imported Live2D"

    def _delete_uploaded_profile_files(self, profile: dict):
        if profile.get("source") != "upload":
            return

        profile_id = profile.get("id")
        if not profile_id:
            return

        root = Path(USER_LIVE2D_DIR).resolve()
        target = (root / profile_id).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            logger.warning(f"Skip unsafe Live2D profile path deletion: {target}")
            return

        model_path = profile.get("model_path", "")
        parsed_path = urlparse(model_path).path
        expected_prefix = f"/user_live2d/{profile_id}/"
        if parsed_path and not parsed_path.startswith(expected_prefix):
            logger.warning(f"Skip Live2D file deletion for unexpected model_path: {model_path}")
            return

        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:
                logger.warning(f"Failed to delete uploaded Live2D files {target}: {e}")

    def _get_current_profile(self) -> dict:
        profiles_config = self._load_profiles_config()
        current_profile_id = profiles_config.get("current_profile_id")
        profiles = profiles_config.get("profiles", [])
        current_profile = next(
            (profile for profile in profiles if profile.get("id") == current_profile_id),
            None,
        )
        if current_profile:
            return current_profile
        if profiles:
            return profiles[0]
        return {
            "id": "default",
            "name": "Default",
            "model_path": settings.LIVE2D_MODEL_PATH,
        }

    def _setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        @self.app.on_event("startup")
        async def startup_event():
            self.loop = asyncio.get_running_loop()
            logger.info(f">>> [DEBUG] Asyncio loop initialized: {self.loop}")

        # Mount audio directory
        audio_dir = "data/audio"
        os.makedirs(audio_dir, exist_ok=True)
        self.app.mount("/audio", StaticFiles(directory=audio_dir), name="audio")

        os.makedirs(USER_LIVE2D_DIR, exist_ok=True)
        self.app.mount(
            "/user_live2d",
            StaticFiles(directory=USER_LIVE2D_DIR),
            name="user_live2d",
        )

        @self.app.get("/config")
        async def get_config():
            current_profile = self._get_current_profile()
            return {
                "character_name": "Ember",
                "display_name": settings.CHARACTER_NAME,
                "state": self.state_manager.current_state,
                "logical_time": self.event_bus.formatted_logical_now,
                "is_thinking": self.state_manager.is_thinking,
                "time_accel_factor": self.event_bus.time_accel_factor,
                "live2d": {
                    "profile_id": current_profile.get("id"),
                    "model_path": current_profile.get(
                        "model_path", settings.LIVE2D_MODEL_PATH
                    ),
                    "display": current_profile.get("display"),
                },
            }

        class TimeAccelRequest(BaseModel):
            factor: float

        class ProfileSelectRequest(BaseModel):
            profile_id: str

        class ProfileDisplayRequest(BaseModel):
            profile_id: str
            display: dict

        class ProfileDeleteRequest(BaseModel):
            profile_id: str

        @self.app.post("/config/time_accel")
        async def set_time_accel(request: TimeAccelRequest):
            """动态设置时间加速因子"""
            if request.factor <= 0:
                raise HTTPException(status_code=400, detail="时间加速因子必须大于0")

            success = self.event_bus.set_time_accel_factor(request.factor)
            if success:
                return {
                    "success": True,
                    "time_accel_factor": self.event_bus.time_accel_factor,
                    "logical_time": self.event_bus.formatted_logical_now,
                }
            else:
                raise HTTPException(status_code=500, detail="设置时间加速因子失败")

        @self.app.get("/history")
        async def get_history(limit: int = 20, before: int = None, before_id: int = None):
            try:
                return self.db_memory.get_history(limit=limit, before_timestamp=before, before_id=before_id)
            except Exception as e:
                logger.error(f"Failed to fetch history: {e}")
                return []

        # ==================== 存档 API ====================

        @self.app.get("/api/profiles")
        async def get_profiles():
            profiles_config = self._load_profiles_config()
            return {
                "current_profile_id": profiles_config.get("current_profile_id"),
                "profiles": profiles_config.get("profiles", []),
            }

        @self.app.post("/api/profiles/select")
        async def select_profile(request: ProfileSelectRequest):
            profiles_config = self._load_profiles_config()
            profiles = profiles_config.get("profiles", [])
            profile = next(
                (
                    profile
                    for profile in profiles
                    if profile.get("id") == request.profile_id
                ),
                None,
            )
            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")

            profiles_config["current_profile_id"] = request.profile_id
            self._save_profiles_config(profiles_config)
            return {
                "success": True,
                "current_profile_id": request.profile_id,
                "profile": profile,
            }

        @self.app.post("/api/profiles/display")
        async def update_profile_display(request: ProfileDisplayRequest):
            profiles_config = self._load_profiles_config()
            profiles = profiles_config.get("profiles", [])
            profile = next(
                (
                    profile
                    for profile in profiles
                    if profile.get("id") == request.profile_id
                ),
                None,
            )
            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")

            profile["display"] = self._normalize_profile_display(request.display)
            self._save_profiles_config(profiles_config)
            return {
                "success": True,
                "profile": profile,
            }

        @self.app.post("/api/profiles/upload-live2d")
        async def upload_live2d_profile(
            file: UploadFile = File(...),
            name: Optional[str] = Form(None),
        ):
            filename = file.filename or ""
            if not filename.lower().endswith(".zip"):
                raise HTTPException(status_code=400, detail="只支持上传 .zip 文件")

            with tempfile.TemporaryDirectory(prefix="ember_live2d_") as temp_dir:
                temp_root = Path(temp_dir)
                zip_path = temp_root / "upload.zip"
                extract_root = temp_root / "extracted"

                await self._save_limited_upload(file, zip_path)
                model_files = self._validate_and_extract_live2d_zip(zip_path, extract_root)

                if not model_files:
                    raise HTTPException(status_code=400, detail="ZIP 中未找到 .model3.json")
                if len(model_files) > 1:
                    raise HTTPException(status_code=400, detail="暂不支持多模型包")

                profile_id = f"custom_{int(time.time())}_{uuid.uuid4().hex[:8]}"
                final_dir = Path(USER_LIVE2D_DIR) / profile_id
                if final_dir.exists():
                    raise HTTPException(status_code=409, detail="模型目录已存在，请重试")

                model_rel_path = model_files[0].relative_to(extract_root).as_posix()
                shutil.move(str(extract_root), str(final_dir))

            profile = {
                "id": profile_id,
                "name": self._build_uploaded_profile_name(file, name),
                "model_path": f"http://localhost:8000/user_live2d/{profile_id}/{model_rel_path}",
                "display": self._normalize_profile_display(DEFAULT_PROFILE_DISPLAY),
                "source": "upload",
            }

            profiles_config = self._load_profiles_config()
            profiles_config.setdefault("profiles", []).append(profile)
            if "current_profile_id" not in profiles_config:
                profiles_config["current_profile_id"] = ""
            self._save_profiles_config(profiles_config)

            return {"success": True, "profile": profile}

        @self.app.post("/api/profiles/delete")
        async def delete_profile(request: ProfileDeleteRequest):
            profiles_config = self._load_profiles_config()
            profiles = profiles_config.get("profiles", [])
            if len(profiles) <= 1:
                raise HTTPException(status_code=400, detail="至少需要保留一个 Live2D 模型")

            profile_index = next(
                (
                    index
                    for index, profile in enumerate(profiles)
                    if profile.get("id") == request.profile_id
                ),
                None,
            )
            if profile_index is None:
                raise HTTPException(status_code=404, detail="Profile not found")

            deleted_profile = profiles.pop(profile_index)
            current_profile_id = profiles_config.get("current_profile_id")
            if current_profile_id == request.profile_id:
                profiles_config["current_profile_id"] = profiles[0].get("id", "")

            self._save_profiles_config(profiles_config)
            self._delete_uploaded_profile_files(deleted_profile)

            return {
                "success": True,
                "current_profile_id": profiles_config.get("current_profile_id"),
                "deleted_profile_id": request.profile_id,
            }

        class ArchiveCreateRequest(BaseModel):
            slot_name: str
            description: Optional[str] = ""

        class ArchiveLoadRequest(BaseModel):
            slot_name: str

        @self.app.get("/api/archive/list")
        async def list_archives():
            """获取存档列表"""
            try:
                slots = self.archive_manager.list_archives()
                return {
                    "success": True,
                    "archives": [slot.to_dict() for slot in slots],
                }
            except Exception as e:
                logger.error(f"获取存档列表失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/archive/create")
        async def create_archive(request: ArchiveCreateRequest):
            """创建存档"""
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.archive_manager.create_archive,
                    request.slot_name,
                    request.description or "",
                )
                return result.to_dict()
            except Exception as e:
                logger.error(f"创建存档失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/archive/load")
        async def load_archive(request: ArchiveLoadRequest):
            """加载存档"""
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.archive_manager.load_archive,
                    request.slot_name,
                )
                return result.to_dict()
            except Exception as e:
                logger.error(f"加载存档失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.delete("/api/archive/{slot_name}")
        async def delete_archive(slot_name: str):
            """删除存档"""
            try:
                result = self.archive_manager.delete_archive(slot_name)
                return result.to_dict()
            except Exception as e:
                logger.error(f"删除存档失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/archive/{slot_name}/preview")
        async def preview_archive(slot_name: str):
            """预览存档信息"""
            try:
                manifest = self.archive_manager.get_archive_preview(slot_name)
                if manifest:
                    return {"success": True, "manifest": manifest.to_dict()}
                else:
                    raise HTTPException(status_code=404, detail="存档不存在")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"预览存档失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/archive/quick-save")
        async def quick_save():
            """快速存档"""
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.archive_manager.quick_save,
                )
                return result.to_dict()
            except Exception as e:
                logger.error(f"快速存档失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/archive/quick-load")
        async def quick_load():
            """快速读档"""
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.archive_manager.quick_load,
                )
                return result.to_dict()
            except Exception as e:
                logger.error(f"快速读档失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.websocket("/ws/chat")
        async def websocket_endpoint(websocket: WebSocket):
            await self.manager.connect(websocket)
            last_ping = time.time()
            ping_interval = 30  # 30秒发送一次心跳

            try:
                while True:
                    # 检查是否需要发送心跳
                    if time.time() - last_ping > ping_interval:
                        try:
                            await websocket.send_text(json.dumps({"type": "ping"}))
                            last_ping = time.time()
                        except Exception:
                            break  # 发送失败，连接已断开

                    # 使用超时接收，避免阻塞
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_text(), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        continue  # 超时继续循环，检查心跳

                    message = json.loads(data)
                    msg_type = message.get("type")

                    # 处理心跳 pong
                    if msg_type == "pong":
                        continue

                    # 严格拦截 TTS 请求，防止进入消息广播逻辑
                    if msg_type == "tts_request":
                        text = message.get("content")
                        if text:
                            logger.info(f"收到手动 TTS 请求: {text[:20]}...")
                            asyncio.create_task(self._process_tts(text))
                        continue  # 必须 continue，跳过下方的 user_input 处理

                    user_input = message.get("content")
                    if user_input:
                        ts = int(self.event_bus.logical_now * 1000)
                        await self.manager.broadcast(
                            {
                                "type": "message",
                                "sender": "user",
                                "content": user_input,
                                "timestamp": ts,
                                "id": ts,
                            }
                        )
                        self.event_bus.publish(
                            Event(name="user.input", data={"text": user_input})
                        )
            except WebSocketDisconnect:
                self.manager.disconnect(websocket)
            except Exception as e:
                logger.error(f"WS loop exception: {e}")
                self.manager.disconnect(websocket)
            finally:
                # 确保连接被移除
                self.manager.disconnect(websocket)

    def _setup_event_handlers(self):
        self.event_bus.subscribe("llm.started", self._on_ai_start_internal)
        self.event_bus.subscribe("llm.chunk", self._on_ai_chunk_internal)
        self.event_bus.subscribe("llm.finished", self._on_ai_finished_internal)
        self.event_bus.subscribe(
            "state.update",
            lambda e: self.safe_broadcast(
                {"type": "state_update", "state": e.data.get("new_state", {})}
            ),
        )

    def _on_ai_start_internal(self, event):
        self.current_ai_msg_id = int(self.event_bus.logical_now * 1000)
        self.current_full_text = ""
        self.safe_broadcast(
            {
                "type": "message",
                "sender": "ai",
                "content": "",
                "mode": "start",
                "timestamp": self.current_ai_msg_id,
                "id": self.current_ai_msg_id,
            }
        )

    def _on_ai_chunk_internal(self, event):
        if self.current_ai_msg_id:
            chunk = event.data.get("text", "")
            self.current_full_text += chunk
            self.safe_broadcast(
                {
                    "type": "message",
                    "sender": "ai",
                    "content": chunk,
                    "mode": "append",
                    "id": self.current_ai_msg_id,
                }
            )

    def _on_ai_finished_internal(self, event):
        logger.info(
            f"LLM 完成输出，准备合成 TTS... (内容长度: {len(self.current_full_text)})"
        )
        if self.current_full_text and self.current_full_text.strip():
            # 只有开启了某种自动逻辑或当前处于 AI 回复流中才自动合成
            if self.loop:
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(
                        self._process_tts(self.current_full_text)
                    )
                )

        self.safe_broadcast({"type": "llm.done"})

    async def _process_tts(self, text):
        """处理 TTS，限制并发数量"""
        if not text or not text.strip():
            return

        # 使用信号量限制并发
        async with self._tts_semaphore:
            try:
                # 限制文本长度，防止超长文本导致性能问题
                max_tts_length = 500
                if len(text) > max_tts_length:
                    text = text[:max_tts_length] + "..."
                    logger.warning(f"TTS 文本过长，已截断至 {max_tts_length} 字符")

                base64_audio = await self.tts_manager.generate_base64(text)
                logger.info(f"广播 Base64 TTS 音频 (长度: {len(base64_audio)})")
                await self.manager.broadcast(
                    {"type": "audio", "audio_base64": base64_audio}
                )
            except Exception as e:
                logger.error(f"TTS 广播错误: {e}")

    def safe_broadcast(self, message: dict):
        """线程安全的广播方法"""
        if self.loop and self.loop.is_running():
            try:
                # 使用 call_soon_threadsafe 安排协程创建
                def create_task():
                    try:
                        asyncio.create_task(self.manager.broadcast(message))
                    except Exception as e:
                        logger.error(f"创建广播任务失败: {e}")

                self.loop.call_soon_threadsafe(create_task)
            except Exception as e:
                logger.error(f"safe_broadcast 失败: {e}")

    def start(self):
        self.heartbeat.start()
        import uvicorn

        logger.info(">>> Ember Server starting...")
        uvicorn.run(self.app, host="0.0.0.0", port=8000, loop="asyncio")


if __name__ == "__main__":
    server = EmberServer()
    server.start()
