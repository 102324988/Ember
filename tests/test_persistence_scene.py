import copy
import json
import uuid
from unittest.mock import Mock, patch
import pytest
from core.event_bus import EventBus, Event
from core.time_utils import to_epoch
from config.settings import settings
from memory.postgres import connection, sync_sequence
from memory.db_memory import DBMemory
from memory.short_term import ShortTermMemory
from persona.scene import normalize_scene, validate_scene, has_time_conflict
from persona.state_manager import StateManager


@pytest.fixture
def clean_db():
    assert settings.PG_DB.startswith('ember_test_')
    with connection() as conn, conn.cursor() as cur:
        cur.execute('TRUNCATE message_list,state_list,episodic_memory RESTART IDENTITY')


def test_history_write_replay_and_timestamp(clean_db):
    bus = EventBus()
    db = DBMemory(bus)
    try:
        key = str(uuid.uuid4())
        ts = int(to_epoch('2026-10-08 16:28:01') * 1000)
        event = Event('user.input', {'text': '持久化测试', 'message_id': key, 'timestamp': ts})
        bus.publish(event)
        assert db.flush()
        bus.publish(event)
        assert db.flush()
        rows = db.get_history()
        assert len(rows) == 1
        assert rows[0]['message_id'] == key
        assert rows[0]['timestamp'] == ts
    finally:
        db.stop()


def test_failed_write_survives_restart(clean_db):
    bus = EventBus()
    db = DBMemory(bus)
    key = str(uuid.uuid4())
    try:
        db.MAX_ATTEMPTS = 1
        with patch.object(db, '_write', side_effect=RuntimeError('disconnect')):
            bus.publish(Event('user.input', {'text': '保存后重试', 'message_id': key}))
            db.store_queue.join()
        assert (db.spool_dir / (key + '.json')).exists()
    finally:
        db.stop()
    replacement = DBMemory(EventBus())
    try:
        assert replacement.flush()
        assert replacement.get_history()[0]['message_id'] == key
    finally:
        replacement.stop()


def test_history_failure_is_not_empty(clean_db):
    db = DBMemory(EventBus())
    try:
        with patch('memory.db_memory.connection', side_effect=RuntimeError('bad password')):
            with pytest.raises(RuntimeError, match='数据库不可用'):
                db.get_history()
        assert not db.ready
    finally:
        db.stop()


def test_sequence_restoration_and_empty_table(clean_db):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO message_list(id,text) VALUES(137,'old')")
        sync_sequence(conn, 'message_list')
        cur.execute("INSERT INTO message_list(text) VALUES('new') RETURNING id")
        assert cur.fetchone()[0] == 138
        cur.execute('TRUNCATE message_list')
        sync_sequence(conn, 'message_list')
        cur.execute("INSERT INTO message_list(text) VALUES('first') RETURNING id")
        assert cur.fetchone()[0] == 1


def test_legacy_memory_unknown_time_and_thought_only():
    from pathlib import Path
    Path('config/chat_memory.json').write_text(json.dumps([
        {'role': 'user', 'content': '晚安'},
        {'role': 'assistant', 'content': '<thought>睡觉</thought>'}]), encoding='utf-8')
    memory = ShortTermMemory()
    assert len(memory.get_memory()['history']) == 1
    assert memory.get_memory()['history'][0]['timestamp'] is None
    memory.add_message('assistant', '<thought>保持沉默</thought>')
    assert len(memory.get_memory()['history']) == 1


def test_scene_and_clock_constraints():
    now = to_epoch('2026-10-08 16:28:01')
    assert has_time_conflict('深夜01:30，宿舍内', now)
    assert not has_time_conflict('宿舍内，活动待确认', now)
    legacy = {'客观情境': '南苑宿舍内，深夜01:30'}
    scene = normalize_scene(legacy)
    assert scene['character_location'] == '南苑宿舍内'
    assert scene['user_location'] is None
    candidate = {'scene': dict(scene, user_location='南苑宿舍内', communication_mode='face_to_face')}
    assert validate_scene(candidate, legacy, '你好')['user_location'] is None
    candidate['scene_evidence'] = '我也到南苑宿舍内了'
    assert validate_scene(candidate, legacy, '我也到南苑宿舍内了')['communication_mode'] == 'face_to_face'
    candidate['scene'].update(communication_mode='remote', remote_contact_confirmed=True)
    assert validate_scene(candidate, legacy, '我也到南苑宿舍内了')['communication_mode'] == 'unknown'


def make_state_manager():
    bus = EventBus()
    bus.restore_logical_time('2026-10-08 16:28:01')
    tools = Mock()
    tools.build_system_prompt_with_tools.side_effect = lambda prompt: prompt
    tools.remove_tool_calls.side_effect = lambda text: text
    manager = StateManager(bus, Mock(), ShortTermMemory(), tools)
    manager.current_state = {'P': 5, 'A': 5, 'D': 5, '客观情境': '宿舍内，深夜01:30',
        '内心活动': '困了', '近期目标': '明天漫展', '近期综合轨迹': '旧轨迹',
        '对应时间': '2026-05-28 01:30:00', 'scene': normalize_scene({'客观情境': '宿舍内'})}
    return manager


def test_conflict_retry_then_safe_fallback():
    manager = make_state_manager()
    with patch.object(manager, '_ask_llm_with_tools', return_value=json.dumps(manager.current_state)), \
         patch.object(manager.llm_client, '_extract_json', side_effect=json.loads):
        manager.prepare_startup()
    assert manager.ready
    assert manager.current_state['scene_status'] == 'needs_confirmation'
    assert '01:30' not in manager.current_state['客观情境']
    assert manager.current_state['scene']['user_location'] is None


def test_tool_result_consumed_once():
    manager = make_state_manager()
    manager.tool_processor.process_llm_output.return_value = {
        'has_tool_calls': True, 'results_text': '工具结果：以前在图书馆', 'clean_text': ''}
    with patch.object(manager.llm_client, 'one_chat', side_effect=['<tool>query</tool>', '{"P":5}']) as call:
        assert manager._ask_llm_with_tools('system', 'prompt') == '{"P":5}'
        assert call.call_count == 2
        assert '以前在图书馆' in call.call_args.args[1][-1]['content']


def test_restore_clock_and_dynamic_idle_threshold():
    manager = make_state_manager()
    manager.current_state['对应时间'] = '2026-03-06 14:15:00'
    manager.after_restore()
    assert manager.event_bus.formatted_logical_now.startswith('2026-03-06 14:15')
    manager.event_bus.set_time_accel_factor(0.5)
    assert manager.state_update_timeout > 0


def test_reply_is_after_scene_preparation():
    from brain.core import Brain
    manager = make_state_manager()
    order = []
    brain = Brain(manager.event_bus, manager, manager.short_term_memory, Mock(), manager.tool_processor)
    with patch.object(manager, 'prepare_dialogue', side_effect=lambda text: order.append('prepare')), \
         patch.object(brain, '_llm_speak', side_effect=lambda *args, **kwargs: order.append('reply')):
        brain.process_dialogue('我到食堂了')
    assert order == ['prepare', 'reply']


def test_complex_archive_round_trip_and_next_insert(clean_db, tmp_path):
    from archive.exporters.postgres_exporter import PostgresExporter
    from archive.importers.postgres_importer import PostgresImporter
    text = "中文, apostrophe's (parentheses);\nsecond line\n-- not a comment"
    with connection() as conn, conn.cursor() as cur:
        cur.execute('INSERT INTO message_list(id,text,timestamp,message_id) VALUES(%s,%s,%s,%s)',
                    (137, text, '2026-10-08 16:28:01', 'roundtrip'))
    assert PostgresExporter(str(tmp_path)).run().success
    result = PostgresImporter(str(tmp_path)).run()
    assert result.success, result.error
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT text FROM message_list WHERE id=137')
        assert cur.fetchone()[0] == text
        cur.execute("INSERT INTO message_list(text,message_id) VALUES('new','next') RETURNING id")
        assert cur.fetchone()[0] == 138


def test_fresh_vector_initialization_encoding_and_recall(clean_db):
    from memory.episodic_memory import EpisodicMemory
    from memory.memory_process import Hippocampus
    from pathlib import Path
    with connection() as conn, conn.cursor() as cur:
        cur.execute('DROP TABLE episodic_memory')
        cur.execute('DROP EXTENSION vector')
    bus = EventBus()
    with patch('memory.episodic_memory.LLMClient') as llm:
        llm.return_value.get_embedding.return_value = [0.1] * 1536
        episodic = EpisodicMemory(bus)
    try:
        assert episodic.ready
        memory = {'content': '在图书馆讨论递归', 'insight': '很开心', 'keywords': ['图书馆'],
                  'importance': 3, 'time': '2026-10-08 16:00:00'}
        with patch('memory.memory_process.LLMClient') as llm:
            llm.return_value.one_chat.return_value = json.dumps([memory], ensure_ascii=False)
            llm.return_value._extract_json.side_effect = json.loads
            hippocampus = Hippocampus(bus)
        Path('config/chat_history.log').write_text('图书馆经历', encoding='utf-8')
        bus.publish(Event('memory.preprocess', {}))
        episodic.store_queue.join()
        assert not any(episodic.spool_dir.glob('*.json'))
        result = hippocampus.query_memory('图书馆递归', ['图书馆'])
        assert result['found']
        assert any('讨论递归' in item for item in result['episodic_memories'])
        assert Path('config/chat_history.log').read_text(encoding='utf-8') == ''
    finally:
        episodic.stop()


def test_idle_clock_changes_do_not_change_real_timeout():
    import time
    manager = make_state_manager()
    manager.ready = True
    manager.last_interaction_real_time = time.monotonic() - 100
    manager.event_bus.set_time_accel_factor(20)
    with patch.object(manager, '_update_state_due_to_idle') as evolve:
        manager._on_tick(Event('system.tick', {}))
        evolve.assert_called_once()


def test_flat_scene_model_output_is_normalized():
    manager = make_state_manager()
    manager.current_state['客观情境'] = '宿舍内，活动待确认'
    text = '我现在在食堂。我们通过微信聊天，已经加过好友。'
    candidate = {'character_location': '宿舍内', 'user_location': '食堂',
                 'communication_mode': 'remote', 'remote_contact_confirmed': True,
                 'scene_evidence': text}
    with patch.object(manager, '_ask_llm_with_tools', return_value=json.dumps(candidate)), \
         patch.object(manager.llm_client, '_extract_json', side_effect=json.loads):
        manager.prepare_dialogue(text)
    assert manager.current_state['scene']['user_location'] == '食堂'
    assert manager.current_state['scene']['communication_mode'] == 'remote'
    assert 'user_location' not in manager.current_state


def test_start_time_iso_and_invalid_warning(monkeypatch):
    monkeypatch.setattr(settings, 'START_TIME', '2026-10-08T01:30:00+08:00')
    assert EventBus().formatted_logical_now.startswith('2026-10-08 01:30')
    monkeypatch.setattr(settings, 'START_TIME', 'invalid')
    EventBus()
    assert any('START_TIME 格式无效' in item for item in settings.CONFIG_WARNINGS)


def test_scene_prepare_broadcasts_only_after_persisting():
    from pathlib import Path
    manager = make_state_manager()
    seen = []
    def on_update(event):
        saved = json.loads(Path('config/state.json').read_text(encoding='utf-8'))
        assert saved == manager.current_state == event.data['new_state']
        seen.append(saved)
    manager.event_bus.subscribe('state.update', on_update)
    state = copy.deepcopy(manager.current_state)
    state['客观情境'] = '宿舍内，活动待确认'
    manager._update_state(state)
    assert len(seen) == 1


def test_archive_waits_for_accepted_dialogues_before_restoring(clean_db):
    from archive import ArchiveManager
    import threading
    import time
    manager = make_state_manager()
    bus = manager.event_bus
    bus.pending_dialogues = 1
    archive = ArchiveManager(event_bus=bus)
    finished = threading.Event()
    def pending_dialogue():
        time.sleep(0.1)
        with bus.pending_condition:
            bus.pending_dialogues = 0
            bus.pending_condition.notify_all()
        finished.set()
    worker = threading.Thread(target=pending_dialogue)
    worker.start()
    archive._pause_system()
    try:
        assert finished.is_set()
        assert bus.paused
    finally:
        archive._resume_system()
        worker.join()
    assert not bus.paused


def test_required_archive_data_failure_is_explicit(clean_db, tmp_path):
    from archive.importers.postgres_importer import PostgresImporter
    result = PostgresImporter(str(tmp_path)).run()
    assert not result.success
    assert '必要数据表' in result.error
