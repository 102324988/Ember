"""Run stubbed UI protocol checks without Docker, models or business configuration."""
import importlib.util
import logging
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    test_root = root / 'frontend' / 'test-results'
    test_root.mkdir(parents=True, exist_ok=True)
    original = Path.cwd()
    checks = (
        'test_failed_write_never_acknowledges_saved_and_replay_acknowledges_success',
        'test_invalid_input_id_cannot_be_used_as_a_spool_path',
        'test_manual_audio_is_targeted_and_never_reads_monologue',
        'test_retried_input_is_acknowledged_without_running_dialogue_twice',
        'test_retry_after_restart_uses_saved_message_and_database_failure_is_visible',
        'test_tts_failure_returns_a_request_correlated_error',
    )
    if not __debug__:
        raise RuntimeError('Run tests without the Python -O option')
    with tempfile.TemporaryDirectory(prefix='protocol-', dir=test_root) as workspace:
        if not Path(workspace).resolve().is_relative_to(test_root.resolve()):
            raise RuntimeError('Temporary test directory is outside the workspace')
        try:
            os.chdir(workspace)
            sys.path.insert(0, str(root))
            os.environ.update(PG_HOST='127.0.0.1', PG_PORT='9', PG_DB='ember_test_protocol_stub',
                PG_PASSWORD='synthetic', ENABLE_NEO4J='False', START_TIME='', TIMEZONE='Asia/Shanghai')
            for prefix in ('LARGE_LLM', 'SMALL_LLM', 'EMBEDDING'):
                os.environ[prefix + '_API_KEY'] = 'synthetic'
                os.environ[prefix + '_BASE_URL'] = 'http://127.0.0.1:9/v1'
                os.environ[prefix + '_MODEL'] = 'synthetic'
            # Do not load the project's .env or permit accidental real DB access.
            with patch('dotenv.load_dotenv', return_value=False), \
                 patch('psycopg2.connect', side_effect=AssertionError('Real databases are disabled in stub checks')):
                spec = importlib.util.spec_from_file_location('protocol_checks', root / 'tests' / 'test_frontend_protocol.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for name in checks:
                    getattr(module, name)()
                    print('PASS ' + name, flush=True)
        finally:
            logging.shutdown()
            os.chdir(original)
    print(f'{len(checks)} stub protocol checks passed. Database integration was not run.')


if __name__ == '__main__':
    main()
