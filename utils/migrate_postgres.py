"""Restore the repair snapshot into an EMPTY target; never changes the source."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg2 import sql
from memory.postgres import connection, initialize_history, initialize_episodic, sync_sequence


def migrate(snapshot_path):
    snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    report = {}
    with connection() as conn:
        initialize_history(conn)
        initialize_episodic(conn)
        with conn.cursor() as cur:
            for table in ('message_list', 'state_list', 'episodic_memory'):
                cur.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table)))
                if cur.fetchone()[0]:
                    raise RuntimeError(f'Target {table} is not empty; migration aborted')
            for table, data in snapshot.items():
                if table not in ('message_list', 'state_list', 'episodic_memory'):
                    raise ValueError('Unexpected snapshot table')
                columns = sql.SQL(',').join(map(sql.Identifier, data['columns']))
                query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(table), columns, sql.SQL(',').join(sql.Placeholder() for _ in data['columns']))
                cur.executemany(query, data['rows'])
                cur.execute(sql.SQL('SELECT {} FROM {} ORDER BY id').format(columns, sql.Identifier(table)))
                actual = [[str(v) if v is not None else None for v in row] for row in cur.fetchall()]
                expected = [[str(v) if v is not None else None for v in row] for row in data['rows']]
                if actual != expected:
                    raise RuntimeError(f'Content verification failed: {table}')
                sync_sequence(conn, table)
                report[table] = {'rows': len(actual), 'verified': True,
                    'sha256': hashlib.sha256(json.dumps(actual, ensure_ascii=False).encode()).hexdigest()}
        initialize_history(conn)
    Path(snapshot_path).with_name('migration_report.json').write_text(
        json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot', help='Path to database.json in the repair backup')
    print(json.dumps(migrate(parser.parse_args().snapshot), indent=2))
