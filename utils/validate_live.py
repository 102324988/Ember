"""Small real-model smoke test in a disposable database and workspace."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
import psycopg2
from psycopg2 import sql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    values = dotenv_values(ROOT / '.env')
    args = dict(host=values['PG_HOST'], port=values['PG_PORT'], user=values['PG_USER'],
                password=values['PG_PASSWORD'], dbname='postgres')
    name = 'ember_test_live_' + uuid.uuid4().hex
    admin = psycopg2.connect(**args)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    report = {}
    try:
        with tempfile.TemporaryDirectory(prefix='ember-live-', ignore_cleanup_errors=True) as temporary:
            # Synthetic inputs only: never send the user's state, history, or persona to a smoke test.
            import yaml
            directory = Path(temporary) / 'config'
            directory.mkdir()
            prompts = {
                'core_persona': '你是名叫依鸣的虚构测试角色。',
                'system_prompt': '按照系统时钟和结构化场景回答，不能猜用户位置。输出 <thought>简短角色独白</thought> 然后说出口的回复。',
                'state_update_prompt': '根据本轮用户明确输入更新场景，输出完整状态 JSON。',
                'idle_state_update_prompt': '只推演角色自己的活动，用户信息保持未知。输出完整状态 JSON。',
            }
            directory.joinpath('prompts.yaml').write_text(yaml.safe_dump(prompts, allow_unicode=True), encoding='utf-8')
            state = {'P':5, 'A':5, 'D':5, '客观情境':'测试宿舍内，深夜01:30',
                '近期综合轨迹':'合成历史', '内心活动':'测试状态', '近期目标':'确认当前活动',
                '对应时间':'2026-05-28 01:30:00', 'scene': {'character_location':'测试宿舍',
                'user_location':None, 'communication_mode':'unknown', 'remote_contact_confirmed':False}}
            directory.joinpath('state.json').write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            directory.joinpath('chat_memory.json').write_text('[]', encoding='utf-8')
            os.environ.update({key: value for key, value in values.items() if value is not None})
            os.environ.update(PG_DB=name, ENABLE_NEO4J='False', START_TIME='')
            os.chdir(temporary)
            from fastapi.testclient import TestClient
            from server import EmberServer
            server = EmberServer()
            responses = []
            original_chat = server.state_manager.llm_client.one_chat
            def capture(*args, **kwargs):
                response = original_chat(*args, **kwargs)
                responses.append({'type': kwargs.get('call_type'), 'response': response})
                return response
            server.state_manager.llm_client.one_chat = capture
            server.heartbeat.interval = 3600
            print('Preparing startup scene with real small model...', flush=True)
            with TestClient(server.app) as client:
                config = client.get('/config').json()
                assert config['status']['database']['ready']
                assert config['status']['long_term_memory']['ready']
                with client.websocket_connect('/ws/chat') as ws:
                    for prompt in ('现在几点？请按系统提供的准确时间回答。',
                                   '我现在在食堂。我们通过微信聊天，已经加过好友。你还在宿舍吗？'):
                        print('Checking real dialogue...', flush=True)
                        ws.send_json({'content': prompt, 'format': 'text'})
                        final = ''
                        while True:
                            message = ws.receive_json()
                            if message.get('type') == 'ping':
                                ws.send_json({'type': 'pong'})
                            if message.get('type') == 'message' and message.get('mode') == 'replace':
                                final = message['content']
                            if message.get('type') == 'llm.done':
                                break
                        from brain.tag_utils import extract_thought_and_speech
                        print('Reply:', extract_thought_and_speech(final)[1], flush=True)
                assert server.db_memory.flush()
                history = client.get('/history').json()
                scene = client.get('/config').json()['state']['scene']
                debug = ROOT / 'data' / 'backups' / 'live_validation_debug.json'
                debug.write_text(json.dumps(responses, ensure_ascii=False, indent=2), encoding='utf-8')
                print('Validated scene:', json.dumps(scene, ensure_ascii=False), flush=True)
                assert len(history) == 4
                assert len({row['message_id'] for row in history}) == 4
                assert scene['user_location'] == '食堂', scene
                assert scene['communication_mode'] == 'remote', scene
                assert scene['remote_contact_confirmed'] is True
                report = {'messages': len(history), 'scene': scene,
                          'logical_time': server.event_bus.formatted_logical_now,
                          'startup_scene_status': config['status']['scene']['state']}
            server.episodic_memory.stop()
    finally:
        import logging
        logging.shutdown()
        os.chdir(ROOT)
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()
    target = ROOT / 'data' / 'backups' / 'live_validation.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
