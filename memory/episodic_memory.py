import psycopg2
from psycopg2.extras import Json, execute_values
from pgvector.psycopg2 import register_vector
import numpy as np
import time
import logging
import json
from config.settings import settings
from core.event_bus import EventBus, Event
from brain.llm_client import LLMClient
import threading
from queue import Empty, Queue
from concurrent.futures import ThreadPoolExecutor
from memory.db_pool import get_connection


logger = logging.getLogger(__name__)


class EpisodicMemory:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._init_db()

        self.store_queue = Queue()
        self.llm_client = LLMClient()

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

        self.event_bus.subscribe("memory.store", self._on_store_request)
        self.event_bus.subscribe("memory.query", self._on_query_request)
        self.event_bus.subscribe("memory.sleep", self._sleep_memory_process)

    def _init_db(self):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    register_vector(conn)

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS episodic_memory(
                            id SERIAL PRIMARY KEY,
                            content TEXT NOT NULL,
                            embedding vector(1536),
                            insight TEXT,
                            insight_embedding vector(1536),
                            importance FLOAT DEFAULT 1.0,
                            confidence FLOAT DEFAULT 1.0,
                            clarity FLOAT DEFAULT 1.0,
                            access_count INTEGER DEFAULT 0,
                            last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            metadata JSONB,
                            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            is_consolidated INTEGER DEFAULT 0
                        )
                        """
                    )
                    cur.execute(
                        """
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'episodic_memory'
                                AND column_name = 'is_consolidated'
                            ) THEN
                                ALTER TABLE episodic_memory ADD COLUMN is_consolidated INTEGER DEFAULT 0;
                            END IF;
                        END $$;
                        """
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to init DB: {e}")

    def _on_store_request(self, event: Event):
        self.store_queue.put({"type": "store", "data": event.data})

    def _worker_loop(self):
        """工作线程循环，支持优雅退出"""
        while True:
            try:
                # 使用 timeout 支持中断
                task = self.store_queue.get(timeout=1.0)
            except Empty:
                # 超时检查是否应该退出
                continue

            if task is None:
                break

            try:
                if task["type"] == "store":
                    self._async_store_process(task["data"])
                elif task["type"] == "update_access":
                    self._execute_update_access(task["id"])
            except Exception as e:
                logger.error(f"Error in EpisodicMemory worker loop: {e}")
            finally:
                try:
                    self.store_queue.task_done()
                except ValueError:
                    pass

    def _async_store_process(self, event_data):
        content = event_data.get("content", "")
        insight = event_data.get("insight", "")

        try:
            embedding = self.llm_client.get_embedding(settings.EMBEDDING_MODEL, content)
            insight_embedding = self.llm_client.get_embedding(
                settings.EMBEDDING_MODEL, insight
            )

            if embedding is None or insight_embedding is None:
                logger.warning(
                    "Failed to get embeddings from LLM, skipping memory store."
                )
                return

            event_data["embedding"] = embedding
            event_data["insight_embedding"] = insight_embedding

            self._add_memory(event_data)
        except Exception as e:
            logger.error(f"Failed to process memory store request: {e}")

    def _on_query_request(self, event: Event):
        query = event.data.get("query", "")
        key_words = event.data.get("key_words", [])
        if not query and not key_words:
            if "callback" in event.data:
                event.data["callback"]([])
            return

        embedding = None
        if query:
            try:
                embedding = self.llm_client.get_embedding(
                    settings.EMBEDDING_MODEL, query
                )
            except Exception as e:
                logger.error(f"Embedding query failed: {e}")

        memories_sim = self._query_by_similarity(embedding) if embedding else []
        memories_key = self._query_by_keywords(key_words) if key_words else []

        seen_ids = set()
        combined_memories = []
        for m in memories_sim + memories_key:
            if m["id"] not in seen_ids:
                logger.debug(f"Memory matched: {m['content'][:50]}... (ID: {m['id']})")
                combined_memories.append(m)
                seen_ids.add(m["id"])

        if "callback" in event.data:
            event.data["callback"](combined_memories)

        for m_id in seen_ids:
            self.store_queue.put({"type": "update_access", "id": m_id})

    def _execute_update_access(self, event_id):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE episodic_memory 
                        SET access_count = access_count + 1,
                            last_accessed = CURRENT_TIMESTAMP,
                            clarity = LEAST(5.0, clarity + (importance * exp(-clarity / 1)))
                        WHERE id = %s
                        """,
                        (event_id,),
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to update access count for memory {event_id}: {e}")

    def _sleep_memory_process(self, event: Event):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE episodic_memory
                        SET clarity = clarity * exp(
                                -%s / (1.0 + ln(1.0 + access_count))
                            )
                        WHERE clarity > 0.01
                        """,
                        (settings.MEMORY_DECENT_FACTOR,),
                    )
                    cur.execute("DELETE FROM episodic_memory WHERE clarity < 0.05")
                    conn.commit()
                    logger.info("Memory cleanup (deleted low clarity memories) completed.")
        except Exception as e:
            logger.error(f"Memory cleanup failed: {e}")

    def _add_memory(self, event_data):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO episodic_memory (content, embedding, insight, insight_embedding, importance, confidence, metadata, time, last_accessed, clarity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event_data.get("content", ""),
                            event_data.get("embedding"),
                            event_data.get("insight", ""),
                            event_data.get("insight_embedding"),
                            event_data.get("importance", 1.0),
                            event_data.get("confidence", 1.0),
                            Json({"keywords": event_data.get("keywords", [])}),
                            event_data.get("time"),
                            event_data.get("time"),
                            event_data.get("importance", 1.0),
                        ),
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to add memory to DB: {e}")

    def _query_by_similarity(self, query_vector):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, content, insight, importance, confidence, access_count, last_accessed, metadata,
                        (1 - (embedding <=> %s::vector)) as similarity1,
                        (1 - (insight_embedding <=> %s::vector)) as similarity2,
                        time
                        FROM episodic_memory 
                        ORDER BY GREATEST((1 - (embedding <=> %s::vector)), (1 - (insight_embedding <=> %s::vector))) DESC, clarity DESC
                        LIMIT %s
                        """,
                        (
                            query_vector,
                            query_vector,
                            query_vector,
                            query_vector,
                            settings.RECALL_TOP_K,
                        ),
                    )
                    results = cur.fetchall()
                    memories = []
                    for row in results:
                        memories.append(
                            {
                                "id": row[0],
                                "content": row[1],
                                "insight": row[2],
                                "importance": row[3],
                                "confidence": row[4],
                                "metadata": row[7],
                                "time": (
                                    row[10].isoformat()
                                    if hasattr(row[10], "isoformat")
                                    else str(row[10])
                                ),
                            }
                        )
                    return memories
        except Exception as e:
            logger.error(f"Similarity query failed: {e}")
            return []

    def _query_by_keywords(self, keywords: list):
        if not keywords:
            return []
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH keyword_matches AS (
                            SELECT 
                                id, content, insight, importance, confidence, access_count, last_accessed, metadata, clarity, time,
                                (
                                    SELECT count(*) 
                                    FROM jsonb_array_elements_text((metadata->'keywords')::jsonb) as k 
                                    WHERE k = ANY(%s)
                                ) as match_count
                            FROM episodic_memory
                            WHERE (metadata->'keywords')::jsonb ?| %s
                        )
                        SELECT id, content, insight, importance, confidence, access_count, last_accessed, metadata, clarity, time
                        FROM keyword_matches
                        ORDER BY match_count DESC, clarity DESC
                        LIMIT %s
                        """,
                        (keywords, keywords, settings.RECALL_TOP_K),
                    )
                    rows = cur.fetchall()
                    memories = []
                    for row in rows:
                        memories.append(
                            {
                                "id": row[0],
                                "content": row[1],
                                "insight": row[2],
                                "importance": row[3],
                                "confidence": row[4],
                                "metadata": row[7],
                                "time": (
                                    row[9].isoformat()
                                    if hasattr(row[9], "isoformat")
                                    else str(row[9])
                                ),
                            }
                        )
                    return memories
        except Exception as e:
            logger.error(f"Keyword query failed: {e}")
            return []
