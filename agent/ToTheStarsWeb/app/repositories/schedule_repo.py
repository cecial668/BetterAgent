from app.core.date_utils import now_str

PLAN_SELECT = '''
SELECT p.id, p.plan_date, p.title, p.content, p.start_minute, p.end_minute, p.quest_id,
       p.created_at, p.updated_at,
       q.title AS quest_title, q.description AS quest_description,
       q.difficulty AS quest_difficulty, q.category AS quest_category,
       q.points AS quest_points, q.is_required AS quest_required,
       q.is_recurring AS quest_recurring, q.is_completed AS quest_completed,
       q.banked_points AS quest_banked_points, q.assigned_date AS quest_assigned_date
FROM schedule_plans p
LEFT JOIN daily_quests q ON q.id = p.quest_id
'''


class ScheduleRepo:
    """日程计划存取。start_minute / end_minute 为“逻辑日 04:00 起算”的分钟偏移。"""

    def __init__(self, db):
        self.db = db

    def create(self, plan_date, title, content, start_minute, end_minute, quest_id=None):
        now = now_str()
        with self.db.tx() as conn:
            cur = conn.execute(
                'INSERT INTO schedule_plans(plan_date,title,content,start_minute,end_minute,quest_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (plan_date, title, content, int(start_minute), int(end_minute), quest_id, now, now),
            )
            return cur.lastrowid

    def update(self, plan_id, plan_date, title, content, start_minute, end_minute):
        with self.db.tx() as conn:
            conn.execute(
                'UPDATE schedule_plans SET plan_date=?,title=?,content=?,start_minute=?,end_minute=?,updated_at=? WHERE id=?',
                (plan_date, title, content, int(start_minute), int(end_minute), now_str(), plan_id),
            )

    def get(self, plan_id):
        with self.db.connect() as conn:
            row = conn.execute(f'{PLAN_SELECT} WHERE p.id=?', (plan_id,)).fetchone()
            return dict(row) if row else None

    def list_by_date(self, date):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    f'{PLAN_SELECT} WHERE p.plan_date=? ORDER BY p.start_minute ASC, p.end_minute ASC, p.id ASC',
                    (date,),
                ).fetchall()
            ]

    def list_between(self, start_date, end_date):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    f'{PLAN_SELECT} WHERE p.plan_date BETWEEN ? AND ? '
                    'ORDER BY p.plan_date ASC, p.start_minute ASC, p.end_minute ASC, p.id ASC',
                    (start_date, end_date),
                ).fetchall()
            ]

    def list_by_quest(self, quest_id):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    f'{PLAN_SELECT} WHERE p.quest_id=? ORDER BY p.plan_date ASC, p.start_minute ASC',
                    (int(quest_id),),
                ).fetchall()
            ]

    def delete(self, plan_id):
        with self.db.tx() as conn:
            conn.execute('DELETE FROM schedule_plans WHERE id=?', (plan_id,))

    def rename_by_quest(self, quest_id, title, content):
        """委托标题/描述变更后，同步所有绑定计划的展示内容。"""
        with self.db.tx() as conn:
            conn.execute(
                'UPDATE schedule_plans SET title=?, content=?, updated_at=? WHERE quest_id=?',
                (title, content, now_str(), int(quest_id)),
            )

    def unbind_quests(self, quest_ids):
        """委托被删除或归档后，计划保留但不再绑定，自动转为自定义计划。"""
        ids = [int(qid) for qid in quest_ids]
        if not ids:
            return 0
        placeholders = ','.join('?' for _ in ids)
        with self.db.tx() as conn:
            cur = conn.execute(
                f'UPDATE schedule_plans SET quest_id=NULL, updated_at=? WHERE quest_id IN ({placeholders})',
                [now_str(), *ids],
            )
            return cur.rowcount

    def move_quest_plans(self, quest_ids, new_date, conn=None):
        """委托顺延到新日期时，绑定计划的日期一起移动。"""
        ids = [int(qid) for qid in quest_ids]
        if not ids:
            return 0
        placeholders = ','.join('?' for _ in ids)
        own = conn is None
        conn = conn or self.db.connect()
        try:
            cur = conn.execute(
                f'UPDATE schedule_plans SET plan_date=?, updated_at=? WHERE quest_id IN ({placeholders})',
                [new_date, now_str(), *ids],
            )
            if own:
                conn.commit()
            return cur.rowcount
        finally:
            if own:
                conn.close()
