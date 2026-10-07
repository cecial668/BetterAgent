from app.core.date_utils import now_str


class FocusRepo:
    def __init__(self, db):
        self.db = db

    def create(self, business_date, started_at, ended_at, planned_minutes, duration_seconds, category, description):
        created_at = now_str()
        with self.db.tx() as conn:
            cur = conn.execute(
                '''INSERT INTO focus_sessions(
                       business_date, started_at, ended_at, planned_minutes,
                       duration_seconds, category, description, created_at
                   ) VALUES(?,?,?,?,?,?,?,?)''',
                (
                    business_date,
                    started_at,
                    ended_at,
                    int(planned_minutes),
                    int(duration_seconds),
                    category,
                    description,
                    created_at,
                ),
            )
            row = conn.execute('SELECT * FROM focus_sessions WHERE id=?', (cur.lastrowid,)).fetchone()
            return dict(row)

    def list_by_date(self, date, limit=100):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    '''SELECT * FROM focus_sessions
                       WHERE business_date=?
                       ORDER BY started_at DESC, id DESC
                       LIMIT ?''',
                    (date, int(limit)),
                ).fetchall()
            ]

    def list_recent(self, limit=100):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    '''SELECT * FROM focus_sessions
                       ORDER BY started_at DESC, id DESC
                       LIMIT ?''',
                    (int(limit),),
                ).fetchall()
            ]

    def total_by_date(self, date):
        with self.db.connect() as conn:
            row = conn.execute(
                'SELECT COALESCE(SUM(duration_seconds), 0) AS seconds FROM focus_sessions WHERE business_date=?',
                (date,),
            ).fetchone()
            return int(row['seconds'] or 0)

    def total_seconds(self):
        with self.db.connect() as conn:
            row = conn.execute('SELECT COALESCE(SUM(duration_seconds), 0) AS seconds FROM focus_sessions').fetchone()
            return int(row['seconds'] or 0)

    def daily_totals_between(self, start_date, end_date):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    '''SELECT business_date AS date, COALESCE(SUM(duration_seconds), 0) AS seconds
                       FROM focus_sessions
                       WHERE business_date BETWEEN ? AND ?
                       GROUP BY business_date
                       ORDER BY business_date ASC''',
                    (start_date, end_date),
                ).fetchall()
            ]
