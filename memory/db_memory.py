"""Durable idempotent writes; history readers own their database connection."""
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from core.event_bus import EventBus, Event
from brain.tag_utils import extract_thought_and_speech
from memory.postgres import connection, initialize_history

logger = logging.getLogger(__name__)


def separate_thought_and_speech(text):
    thought, speech = extract_thought_and_speech(text)
    return thought, speech if thought else (speech or text.strip())


class DBMemory:
    MAX_ATTEMPTS = 5

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.store_queue = Queue()
        self.ready = False
        self.last_error = None
        self._stop = threading.Event()
        self._pending_lock = threading.Lock()
        self._pending = set()
        self.spool_dir = Path('data/failed_writes')
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        event_bus.subscribe('user.input', self._on_user_input)
        event_bus.subscribe('llm.finished', self._on_llm_finished)
        event_bus.subscribe('llm.interrupted', self._on_llm_interrupted)
        event_bus.subscribe('state.update', self._on_state_update)
        self.retry_failed()
        self.start()

    def _init_db(self):
        try:
            with connection() as conn:
                initialize_history(conn)
            self.ready, self.last_error = True, None
        except Exception as exc:
            self.ready, self.last_error = False, str(exc)
            logger.error('History schema initialization failed: %s', exc)

    def _enqueue(self, table, data):
        data.setdefault('message_id', str(uuid.uuid4()))
        entry = {'database': table, 'data': data}
        file = self.spool_dir / (data['message_id'] + '.json')
        temp = file.with_suffix('.tmp')
        temp.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
        temp.replace(file)
        self._schedule(entry)

    def _schedule(self, entry):
        key = entry['data']['message_id']
        with self._pending_lock:
            if key in self._pending:
                return
            self._pending.add(key)
        self.store_queue.put(entry)

    def retry_failed(self):
        for file in self.spool_dir.glob('*.json'):
            try:
                self._schedule(json.loads(file.read_text(encoding='utf-8')))
            except Exception as exc:
                logger.error('Cannot replay pending database write: %s', exc)

    def _on_user_input(self, event: Event):
        event.data.setdefault('message_id', str(uuid.uuid4()))
        event.data.setdefault('timestamp', int(self.event_bus.logical_now * 1000))
        self._enqueue('message_list', {'sender': 'user', 'text': event.data['text'],
            'thinking': '', 'timestamp': self.event_bus.format_logical_time(event.data['timestamp'] / 1000),
            'message_id': event.data['message_id'], 'turn_id': event.data.get('turn_id')})

    def _on_llm_finished(self, event: Event):
        thought, speech = separate_thought_and_speech(event.data['text'])
        timestamp = event.data.get('timestamp', int(self.event_bus.logical_now * 1000))
        self._enqueue('message_list', {'sender': 'assistant', 'text': speech, 'thinking': thought,
            'timestamp': self.event_bus.format_logical_time(timestamp / 1000),
            'message_id': event.data.get('message_id', str(uuid.uuid4())),
            'completion_status': event.data.get('completion_status', 'completed'), 'turn_id': event.data.get('turn_id')})

    def _on_llm_interrupted(self, event: Event):
        if separate_thought_and_speech(event.data.get('text', ''))[1].strip():
            self._on_llm_finished(event)

    def _on_state_update(self, event: Event):
        self._enqueue('state_list', {'text': json.dumps(event.data['new_state'], ensure_ascii=False),
            'timestamp': event.data['new_state'].get('对应时间', self.event_bus.formatted_logical_now)})

    def start(self):
        self.worker_thread = threading.Thread(target=self._store_loop, daemon=True)
        self.worker_thread.start()

    def get_history(self, limit=20, before_timestamp=None, before_id=None):
        from core.time_utils import to_epoch
        try:
            with connection() as conn, conn.cursor() as cur:
                query = 'SELECT id,timestamp,sender,text,thinking,message_id,completion_status,turn_id FROM message_list'
                args = []
                if before_timestamp is not None:
                    date = datetime.fromtimestamp(float(before_timestamp) / 1000, self.event_bus.timezone).replace(tzinfo=None)
                    if before_id is not None:
                        query += ' WHERE (timestamp,id) < (%s,%s)'
                        args.extend([date, before_id])
                    else:
                        query += ' WHERE timestamp < %s'
                        args.append(date)
                query += ' ORDER BY timestamp DESC,id DESC LIMIT %s'
                args.append(max(1, min(int(limit), 100)))
                cur.execute(query, args)
                rows = cur.fetchall()
            self.ready = True
            return [{'id': row[0], 'timestamp': int(to_epoch(row[1]) * 1000),
                'role': 'ai' if row[2] == 'assistant' else 'user', 'content': row[3] or '',
                'thinking': row[4] or '', 'message_id': row[5] or f'legacy-{row[0]}',
                'completion_status': row[6], 'turn_id': row[7]} for row in rows]
        except Exception as exc:
            self.ready, self.last_error = False, str(exc)
            logger.error('Failed to fetch history: %s', exc)
            raise RuntimeError('聊天记录数据库不可用，请检查后端日志') from exc

    def _write(self, entry):
        data = entry['data']
        with connection() as conn, conn.cursor() as cur:
            if entry['database'] == 'state_list':
                cur.execute('INSERT INTO state_list(text,timestamp,message_id) VALUES(%s,%s,%s) ON CONFLICT(message_id) DO NOTHING',
                    (data['text'], data['timestamp'], data['message_id']))
            elif entry['database'] == 'message_list':
                cur.execute('INSERT INTO message_list(sender,text,thinking,timestamp,message_id,completion_status,turn_id) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING',
                    (data['sender'],data['text'],data['thinking'],data['timestamp'],data['message_id'],
                     data.get('completion_status', 'completed'), data.get('turn_id')))
            else:
                raise ValueError('Unsupported persistence table')

    def get_message(self, message_id):
        """Resolve an explicit retry after a server restart without replaying its dialogue."""
        from core.time_utils import to_epoch
        try:
            pending = self.spool_dir / (message_id + '.json')
            if pending.is_file():
                entry = json.loads(pending.read_text(encoding='utf-8'))
                data = entry['data']
                if entry['database'] == 'message_list' and data['sender'] == 'user':
                    return {'content': data['text'], 'timestamp': int(to_epoch(data['timestamp']) * 1000), 'message_id': data['message_id'], 'persisted': False}
            with connection() as conn, conn.cursor() as cur:
                cur.execute('SELECT text,timestamp,message_id FROM message_list WHERE message_id=%s AND sender=%s', (message_id, 'user'))
                row = cur.fetchone()
            return None if row is None else {'content': row[0], 'timestamp': int(to_epoch(row[1]) * 1000), 'message_id': row[2], 'persisted': True}
        except Exception as exc:
            raise RuntimeError('无法核对原消息') from exc

    def _store_loop(self):
        while not self._stop.is_set():
            try:
                entry = self.store_queue.get(timeout=0.2)
            except Empty:
                continue
            key = entry['data']['message_id']
            try:
                for attempt in range(self.MAX_ATTEMPTS):
                    try:
                        if not self.ready:
                            self._init_db()
                        self._write(entry)
                        (self.spool_dir / (key + '.json')).unlink(missing_ok=True)
                        self.ready, self.last_error = True, None
                        if entry['database'] == 'message_list':
                            self.event_bus.publish(Event('message.persisted', {'message_id': key}))
                        break
                    except Exception as exc:
                        self.ready, self.last_error = False, str(exc)
                        logger.error('Database write failed (%s/%s): %s', attempt + 1, self.MAX_ATTEMPTS, exc)
                        if self._stop.wait(min(2 ** attempt, 5)):
                            break
            finally:
                with self._pending_lock:
                    self._pending.discard(key)
                self.store_queue.task_done()

    def flush(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.store_queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        return not self.store_queue.unfinished_tasks and not any(self.spool_dir.glob('*.json'))

    def stop(self):
        self._stop.set()
        self.worker_thread.join(timeout=6)
