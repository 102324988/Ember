"""Cooperative turn cancellation; terminal state is confirmed by the worker."""
import logging
import threading
import uuid

logger = logging.getLogger(__name__)
TERMINAL = {'completed', 'interrupted', 'failed'}


class TurnCancelled(Exception):
    pass


class Turn:
    def __init__(self, turn_id, timestamp, source='dialogue'):
        self.id = turn_id
        self.message_id = str(uuid.uuid4())
        self.timestamp = timestamp
        self.source = source
        self.status = 'running'
        self.released = False
        self.phase = 'preparing'
        self.partial = ''
        self.cancelled = threading.Event()
        self._lock = threading.RLock()
        self._closer = None

    def check(self):
        if self.cancelled.is_set():
            raise TurnCancelled()

    def set_phase(self, phase):
        with self._lock:
            self.phase = phase

    def snapshot(self):
        with self._lock:
            return {'turn_id': self.id, 'message_id': self.message_id, 'timestamp': self.timestamp,
                'source': self.source, 'status': self.status,
                'released': self.released,
                'phase': 'stopping' if self.status == 'stopping' else self.phase}

    def request_cancel(self):
        with self._lock:
            if self.status in TERMINAL:
                return False
            if self.cancelled.is_set():
                return True
            self.cancelled.set()
            self.status = 'stopping'
            closer = self._closer
        if closer:
            self._close_async(closer)
        return True

    @staticmethod
    def _close_async(closer):
        def close():
            try:
                closer()
            except Exception:
                logger.debug('Cancelled stream was already closed', exc_info=True)
        threading.Thread(target=close, daemon=True, name='cancel-stream').start()

    def attach_stream(self, closer):
        with self._lock:
            self._closer = closer
            cancelled = self.cancelled.is_set()
        if cancelled:
            self._close_async(closer)
            raise TurnCancelled()

    def detach_stream(self):
        with self._lock:
            self._closer = None

    def finish(self, status):
        with self._lock:
            if self.status in TERMINAL:
                return False
            if status == 'completed':
                self.check()
            self.status = status
            return True

    def release(self):
        with self._lock:
            self.released = True


class TurnCoordinator:
    def __init__(self):
        self._lock = threading.RLock()
        self.current = None

    def begin(self, timestamp, turn_id=None, source='dialogue'):
        with self._lock:
            if self.current and (self.current.status not in TERMINAL or not self.current.released):
                if turn_id == self.current.id:
                    return self.current
                raise RuntimeError('Another turn is still running')
            self.current = Turn(turn_id or str(uuid.uuid4()), timestamp, source)
            return self.current

    def snapshot(self):
        with self._lock:
            return self.current.snapshot() if self.current else None

    def cancel(self, turn_id):
        with self._lock:
            if not self.current or self.current.id != turn_id:
                return None
            self.current.request_cancel()
            return self.current.snapshot()
