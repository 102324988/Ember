import json
import threading
import os
import re
import copy
from concurrent.futures import ThreadPoolExecutor
from brain.tag_utils import extract_thought_and_speech
from config.settings import settings


def separate_thought_and_speech(text):
    """分离 thought 和 speech（使用增强的容错处理）"""
    thought, speech = extract_thought_and_speech(text)
    # 如果没有提取到 speech，返回原始文本
    if not speech:
        speech = text.strip()
    from brain.tag_utils import remove_speech_tags
    speech = remove_speech_tags(speech)
    return thought, speech


class ShortTermMemory:
    # 类级别线程池，所有实例共享
    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="short_term")

    def __init__(self, max_memory_size=20, base_prompt=None, state="initial"):
        self.max_memory_size = max_memory_size
        self.memory = []
        self._memory_lock = threading.RLock()
        self.base_prompt = "你是一名助手"
        if base_prompt:
            self.base_prompt = base_prompt
        self.current_state = state
        self._load_memory()

    def _load_memory(self):
        try:
            if os.path.exists("./config/chat_memory.json"):
                with open("./config/chat_memory.json", "r", encoding="utf-8") as f:
                    self.memory = json.load(f)
                    self._truncate_memory()
        except Exception as e:
            print(f"Error loading memory: {e}")

    def _add_front(self, role, content):
        self.memory.insert(0, {"role": role, "content": content})
        self._truncate_memory()

    def _add_back(self, role, content, timestamp=None):
        msg = {"role": role, "content": content}
        if timestamp:
            msg["timestamp"] = timestamp
        self.memory.append(msg)
        self._truncate_memory()

    def _truncate_memory(self):
        if len(self.memory) > self.max_memory_size:
            self.memory = self.memory[-self.max_memory_size :]

    def async_log(self, filename, content):
        def _log():
            try:
                with open(filename, "a", encoding="utf-8", buffering=1) as f:
                    f.write(content + "\n")
            except Exception as e:
                print(f"Error writing log: {e}")

        self._executor.submit(_log)

    def _async_log_clear(self, filename):
        def _log():
            try:
                with open(filename, "w", encoding="utf-8", buffering=1) as f:
                    f.write("")
            except Exception as e:
                print(f"Error clearing log: {e}")

        self._executor.submit(_log)

    def add_message(self, role, content, timestamp=None):
        with self._memory_lock:
            if role == "assistant":
                _, speech = separate_thought_and_speech(content)
                self._add_back(role, speech, timestamp=timestamp)
                self.async_log(
                    "./config/chat_history.log",
                    f"{role}: {speech}",
                )
            else:
                self._add_back(role, content, timestamp=timestamp)
                self.async_log(
                    "./config/chat_history.log",
                    f"{role}: {content}",
                )
        self._save_memory()

    def _save_memory(self):
        with self._memory_lock:
            snapshot = copy.deepcopy(self.memory)

        def _save():
            try:
                with open("./config/chat_memory.json", "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"Error saving memory: {e}")

        self._executor.submit(_save)

    def update_base_prompt(self, new_base_prompt):
        self.base_prompt = new_base_prompt

    def get_full_messages(self):
        with self._memory_lock:
            system_content = self.base_prompt
            timestamped_memory = []
            for msg in self.memory:
                ts = msg.get("timestamp", "")
                if ts:
                    try:
                        short_ts = ts[5:16]  # "MM-DD HH:MM"
                        content = f"[{short_ts}] {msg['content']}"
                    except Exception:
                        content = msg["content"]
                else:
                    content = msg["content"]
                timestamped_memory.append({"role": msg["role"], "content": content})
        return [
            {"role": "system", "content": system_content},
        ] + timestamped_memory

    def get_memory(self):
        with self._memory_lock:
            return {"history": copy.deepcopy(self.memory)}

    def clear_memory(self):
        with self._memory_lock:
            self.memory = []
        self._async_log_clear("./config/chat_history.log")

    def get_last_n_messages(self, n):
        with self._memory_lock:
            if n <= 0:
                return []
            if n >= len(self.memory):
                return copy.deepcopy(self.memory)
            return copy.deepcopy(self.memory[-n:])
