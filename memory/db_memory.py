import psycopg2
from psycopg2.extras import Json, execute_values
from core.event_bus import EventBus, Event
from config.settings import settings
import logging
import json
import threading
import re
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from brain.tag_utils import extract_thought_and_speech
from memory.db_pool import get_connection

logger = logging.getLogger(__name__)


def separate_thought_and_speech(text):
    """分离 thought 和 speech（使用增强的容错处理）"""
    thought, speech = extract_thought_and_speech(text)
    # 如果没有提取到 speech，返回原始文本
    if not speech:
        speech = text.strip()
    return thought, speech


class DBMemory:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.store_queue = Queue()
        self._init_db()
        self.event_bus.subscribe("user.input", self._on_user_input)
        self.event_bus.subscribe("llm.finished", self._on_llm_finished)
        self.event_bus.subscribe("state.update", self._on_state_update)
        self.start()

    def _init_db(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS message_list (
                            id SERIAL PRIMARY KEY,
                            timestamp TIMESTAMP DEFAULT NOW(),
                            sender TEXT,
                            text TEXT,
                            thinking TEXT
                        );
                    """
                    )
                    conn.commit()
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS state_list (
                            id SERIAL PRIMARY KEY,
                            timestamp TIMESTAMP DEFAULT NOW(),
                            text TEXT
                        );
                    """
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize DB: {e}")

    def _on_user_input(self, event: Event):
        data = {
            "sender": "user",
            "text": event.data["text"],
            "thinking": "",
            "timestamp": self.event_bus.formatted_logical_now,
        }
        content = {"data": data, "database": "message_list"}
        self.store_queue.put(content)

    def _on_llm_finished(self, event: Event):
        thought, speech = separate_thought_and_speech(event.data["text"])
        data = {
            "sender": "assistant",
            "text": speech,
            "thinking": thought,
            "timestamp": self.event_bus.formatted_logical_now,
        }
        content = {"data": data, "database": "message_list"}
        self.store_queue.put(content)

    def start(self):
        threading.Thread(target=self._store_loop, daemon=True).start()

    def get_history(self, limit=20, before_timestamp=None, before_id=None):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # 优先使用 before_id（更可靠，避免时区问题）
                    if before_id:
                        cur.execute(
                            """
                            SELECT id, timestamp, sender, text, thinking 
                            FROM message_list 
                            WHERE id < %s
                            ORDER BY id DESC 
                            LIMIT %s
                        """,
                            (before_id, limit),
                        )
                    elif before_timestamp:
                        if isinstance(before_timestamp, (int, float)):
                            query = "SELECT id, timestamp, sender, text, thinking FROM message_list WHERE timestamp < to_timestamp(%s / 1000.0) ORDER BY id DESC LIMIT %s"
                        else:
                            query = "SELECT id, timestamp, sender, text, thinking FROM message_list WHERE timestamp < %s ORDER BY id DESC LIMIT %s"
                        cur.execute(query, (before_timestamp, limit))
                    else:
                        cur.execute(
                            """
                            SELECT id, timestamp, sender, text, thinking 
                            FROM message_list 
                            ORDER BY id DESC 
                            LIMIT %s
                        """,
                            (limit,),
                        )

                    rows = cur.fetchall()
                    messages = []
                    for row in rows:
                        raw_ts = row[1]
                        ts_value = (
                            int(raw_ts.timestamp() * 1000)
                            if hasattr(raw_ts, "timestamp")
                            else 0
                        )

                        messages.append(
                            {
                                "id": row[0],
                                "timestamp": ts_value,
                                "role": "ai" if row[2] == "assistant" else "user",
                                "content": row[3],
                                "thinking": row[4],
                            }
                        )
                    return messages
        except Exception as e:
            logger.error(f"Failed to fetch history: {e}")
            return []

    def _store_loop(self):
        while True:
            content = self.store_queue.get()
            data = content["data"]
            database_name = content.get("database", "message_list")
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        if database_name == "state_list":
                            cur.execute(
                                """
                                INSERT INTO state_list (text, timestamp) 
                                VALUES (%s, %s);
                            """,
                                (data["text"], data["timestamp"]),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO message_list (sender, text, thinking, timestamp) 
                                VALUES (%s, %s, %s, %s);
                            """,
                                (
                                    data["sender"],
                                    data["text"],
                                    data["thinking"],
                                    data["timestamp"],
                                ),
                            )
                        conn.commit()
            except Exception as e:
                logger.error(f"Failed to store message: {e}")

    def _on_state_update(self, event: Event):
        data = {
            "text": json.dumps(event.data["new_state"], ensure_ascii=False),
            "timestamp": self.event_bus.formatted_logical_now,
        }
        content = {"data": data, "database": "state_list"}
        self.store_queue.put(content)
