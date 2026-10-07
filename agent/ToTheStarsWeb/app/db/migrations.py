"""轻量数据库兼容迁移。只做 CREATE IF NOT EXISTS / ALTER ADD COLUMN，不覆盖旧库。"""
from __future__ import annotations

SAFE_COLUMNS = {
    'daily_quests': {
        'banked_points': 'REAL DEFAULT 0',
        'completed_at': 'TEXT',
        'updated_at': 'TEXT',
        'is_recurring': 'INTEGER DEFAULT 0',
    },
    'daily_settlements': {
        'state_bonus': 'REAL DEFAULT 0',
        'summary_json': 'TEXT',
    },
    'daily_states': {
        'reward_granted': 'INTEGER DEFAULT 0',
        'updated_at': 'TEXT',
        'journal_title': "TEXT DEFAULT ''",
        'images_json': "TEXT DEFAULT '[]'",
    },
    'legend_quests': {
        'points_awarded': 'INTEGER DEFAULT 0',
        'updated_at': 'TEXT',
    },
    'rewards': {
        'status': "TEXT DEFAULT 'active'",
        'updated_at': 'TEXT',
    },
    'reward_purchases': {
        'reward_name': 'TEXT',
        'reward_content': 'TEXT',
        'outbound_status': "TEXT DEFAULT 'pending'",
        'outbound_at': 'TEXT',
    },
    'app_sessions': {
        'closed_normally': 'INTEGER DEFAULT 0',
    },
}

def run_migrations(conn):
    for table, columns in SAFE_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
