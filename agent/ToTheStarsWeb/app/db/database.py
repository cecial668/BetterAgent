import sqlite3
from contextlib import contextmanager
from app.core.config import DB_PATH
from app.db.migrations import run_migrations
from app.core.date_utils import now_str

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS daily_quests(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL, description TEXT, difficulty TEXT NOT NULL, points REAL NOT NULL,
 category TEXT, is_required INTEGER DEFAULT 0, is_recurring INTEGER DEFAULT 0, is_completed INTEGER DEFAULT 0,
 assigned_date TEXT NOT NULL, completed_at TEXT, banked_points REAL DEFAULT 0,
 created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS quest_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT, original_quest_id INTEGER, title TEXT, description TEXT,
 difficulty TEXT, points REAL, category TEXT, is_required INTEGER, assigned_date TEXT,
 completed_at TEXT, archived_at TEXT, archive_reason TEXT, settlement_date TEXT
);
CREATE TABLE IF NOT EXISTS daily_settlements(
 date TEXT PRIMARY KEY, is_vacation INTEGER, is_success INTEGER, day_title TEXT,
 total_points REAL, points_banked REAL, state_bonus REAL, required_all_done INTEGER,
 completed_count INTEGER, total_count INTEGER, settled_at TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS point_wallet(
 id INTEGER PRIMARY KEY CHECK(id=1), practice_points REAL DEFAULT 0, growth_points REAL DEFAULT 0, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS point_transactions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, created_at TEXT, point_type TEXT,
 amount REAL, reason TEXT, related_type TEXT, related_id INTEGER, balance_after REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS legend_quests(
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT, difficulty TEXT,
 growth_points REAL, status TEXT DEFAULT 'active', deadline TEXT, created_at TEXT,
 completed_at TEXT, points_awarded INTEGER DEFAULT 0, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS legend_indicators(
 id INTEGER PRIMARY KEY AUTOINCREMENT, legend_id INTEGER, title TEXT NOT NULL, description TEXT,
 is_completed INTEGER DEFAULT 0, completed_at TEXT, created_at TEXT, updated_at TEXT,
 FOREIGN KEY(legend_id) REFERENCES legend_quests(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rewards(
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, content TEXT, point_type TEXT,
 price REAL, stock INTEGER, status TEXT DEFAULT 'active', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS reward_purchases(
 id INTEGER PRIMARY KEY AUTOINCREMENT, reward_id INTEGER, reward_name TEXT, reward_content TEXT,
 purchased_at TEXT, point_type TEXT, price REAL, stock_after INTEGER, balance_after REAL,
 outbound_status TEXT DEFAULT 'pending', outbound_at TEXT
);
CREATE TABLE IF NOT EXISTS daily_states(
 date TEXT PRIMARY KEY, rating INTEGER, emotions TEXT, social_type TEXT,
 social_feeling INTEGER, energy INTEGER, review_text TEXT, reward_granted INTEGER DEFAULT 0,
 journal_title TEXT DEFAULT '', images_json TEXT DEFAULT '[]',
 created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS vacation_days(
 date TEXT PRIMARY KEY, reason TEXT, is_active INTEGER DEFAULT 1, created_at TEXT, canceled_at TEXT
);
CREATE TABLE IF NOT EXISTS app_sessions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, opened_at TEXT, closed_at TEXT, closed_normally INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS operation_logs(
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, action_type TEXT, target_type TEXT, target_id INTEGER, detail TEXT
);
CREATE TABLE IF NOT EXISTS agent_audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 created_at TEXT NOT NULL,
 actor TEXT NOT NULL DEFAULT 'me',
 action TEXT NOT NULL,
 target_type TEXT DEFAULT '',
 target_id INTEGER,
 params_json TEXT DEFAULT '{}',
 result_json TEXT DEFAULT '{}',
 undo_payload_json TEXT DEFAULT '',
 undoable INTEGER DEFAULT 0,
 undone_at TEXT DEFAULT '',
 undo_note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_created_at ON agent_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_audit_actor ON agent_audit(actor);

CREATE TABLE IF NOT EXISTS focus_sessions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 business_date TEXT NOT NULL,
 started_at TEXT NOT NULL,
 ended_at TEXT NOT NULL,
 planned_minutes INTEGER NOT NULL,
 duration_seconds INTEGER NOT NULL,
 category TEXT DEFAULT '未分类',
 description TEXT DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_plans(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 plan_date TEXT NOT NULL,
 title TEXT NOT NULL,
 content TEXT DEFAULT '',
 start_minute INTEGER NOT NULL,
 end_minute INTEGER NOT NULL,
 quest_id INTEGER,
 created_at TEXT,
 updated_at TEXT,
 FOREIGN KEY(quest_id) REFERENCES daily_quests(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_schedule_plans_date ON schedule_plans(plan_date);
CREATE INDEX IF NOT EXISTS idx_schedule_plans_quest ON schedule_plans(quest_id);
CREATE INDEX IF NOT EXISTS idx_daily_quests_assigned_date ON daily_quests(assigned_date);
CREATE INDEX IF NOT EXISTS idx_quest_history_settlement_date ON quest_history(settlement_date);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON point_transactions(date);
CREATE INDEX IF NOT EXISTS idx_focus_sessions_business_date ON focus_sessions(business_date);
CREATE INDEX IF NOT EXISTS idx_focus_sessions_started_at ON focus_sessions(started_at);
"""

class Database:
    def __init__(self, path=DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn
    def init_db(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            run_migrations(conn)
            conn.execute("INSERT OR IGNORE INTO point_wallet(id, practice_points, growth_points, updated_at) VALUES(1,0,0,?)", (now_str(),))
            conn.commit()
    @contextmanager
    def tx(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()
