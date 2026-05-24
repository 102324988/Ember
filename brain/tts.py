import edge_tts
import asyncio
import logging
import os
import time
import re
from brain.tag_utils import remove_thought_content

logger = logging.getLogger("EmberTTS")

class RateLimiter:
    """速率限制器，确保两次请求之间有安全的时间间隔"""
    def __init__(self, min_interval_seconds=3.0):
        self.min_interval = min_interval_seconds
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def wait_if_needed(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()

class TTSManager:
    def __init__(self, voice="zh-CN-XiaoxiaoNeural"):
        self.voice = voice
        self.output_dir = "data/audio"
        os.makedirs(self.output_dir, exist_ok=True)
        # 初始化 3 秒间隔限速器
        self.rate_limiter = RateLimiter(min_interval_seconds=3.0)

    @staticmethod
    def split_sentences(text: str, first_seg_target=40, normal_min=60, normal_max=120, merge_threshold=15) -> list[str]:
        """
        自适应句子切割：首段短 (降低首字延迟)，后续段长 (保证连续播放)
        """
        import re
        text = text.strip()
        if not text:
            return []

        # 预处理：替换中文省略号等组合符号，避免切错
        text = text.replace("……", "。")
        text = re.sub(r'\s+', ' ', text) # 将多余空白符合并

        # 定义分隔符模式
        primary_delims = re.compile(r'([。！？!\?]+)')
        secondary_delims = re.compile(r'([；;]+)')
        tertiary_delims = re.compile(r'([，,]+)')

        # 先按最细粒度（三级即所有标点）切片，然后根据算法拼接
        all_delims = re.compile(r'([。！？!\?；;，,\n]+)')
        parts = all_delims.split(text)
        
        # parts [text1, delim1, text2, delim2...]
        chunks = []
        current_chunk = ""
        for i in range(0, len(parts), 2):
            content = parts[i]
            delim = parts[i+1] if i+1 < len(parts) else ""
            current_chunk += content + delim

            if not current_chunk.strip():
                continue

            current_len = len(current_chunk)
            is_first = len(chunks) == 0

            target_min = 10 if is_first else normal_min
            target_max = first_seg_target if is_first else normal_max

            # 判断是否切割
            should_split = False
            
            if current_len >= target_max:
                # 超过最大限制，必须切
                should_split = True
            elif current_len >= target_min:
                # 达到最小限制，看是否有高级标点
                if is_first:
                    # 首段尽量早切，哪怕是个逗号
                    should_split = True
                elif primary_delims.search(delim) or secondary_delims.search(delim):
                    # 后续段遇到一二级标点才切
                    should_split = True

            if should_split:
                chunks.append(current_chunk.strip())
                current_chunk = ""

        # 最后的残余部分
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # 合并处理：处理过短片段
        final_chunks = []
        for i, chunk in enumerate(chunks):
            if not chunk: continue
            
            if len(chunk) < merge_threshold:
                if final_chunks:
                    # 合并到前一段
                    final_chunks[-1] += " " + chunk
                elif i + 1 < len(chunks):
                    # 如果是开头且没前一段，先放进来，等下一段合并它
                    final_chunks.append(chunk)
                else:
                    final_chunks.append(chunk)
            else:
                final_chunks.append(chunk)

        return final_chunks

    @staticmethod
    def remove_parenthesized_content(text: str) -> str:
        """移除中英文括号及其内容（动作/表情描述，不适合 TTS 朗读）"""
        # 中文全角括号 （...）
        text = re.sub(r'（[^）]*）', '', text)
        # 英文半角括号 (...)
        text = re.sub(r'\([^)]*\)', '', text)
        # 清理多余空白
        return re.sub(r'\s{2,}', ' ', text).strip()

    async def generate_base64(self, text: str, timeout: float = 30.0):
        """合成语音并返回 Base64 编码，带超时保护和限速"""
        import base64

        try:
            clean_text = remove_thought_content(text)
            clean_text = self.remove_parenthesized_content(clean_text)
            if not clean_text.strip():
                return None
                
            audio_data = await self.generate_with_retry(clean_text, timeout=timeout)
            if audio_data:
                return base64.b64encode(audio_data).decode('utf-8')
            return None
        except Exception as e:
            logger.error(f"TTS base64 处理失败: {e}")
            return None

    async def generate_with_retry(self, clean_text: str, timeout: float = 30.0, max_retries: int = 1) -> bytes | None:
        """带退避重试和等待频率限制的合成逻辑"""
        for attempt in range(max_retries + 1):
            await self.rate_limiter.wait_if_needed()
            try:
                # 使用 asyncio.wait_for 包装 TTS 操作
                audio_data = await asyncio.wait_for(
                    self._do_tts(clean_text),
                    timeout=timeout
                )
                return audio_data
            except asyncio.TimeoutError:
                logger.error(f"TTS 合成超时 (>{timeout}s) [尝试 {attempt+1}/{max_retries+1}]")
            except Exception as e:
                logger.error(f"TTS 合成失败: {e} [尝试 {attempt+1}/{max_retries+1}]")
            
            if attempt < max_retries:
                # 指数退避: 1s, 2s...
                await asyncio.sleep(2 ** attempt)
                
        return None

    async def _do_tts(self, clean_text: str):
        """执行实际的 TTS 合成"""
        communicate = edge_tts.Communicate(clean_text, self.voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    def cleanup(self, filename):
        """清理旧的语音文件"""
        filepath = os.path.join(self.output_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)

