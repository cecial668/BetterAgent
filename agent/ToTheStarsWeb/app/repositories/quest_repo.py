from app.core.date_utils import now_str


class QuestRepo:
    def __init__(self, db):
        self.db = db

    def list_by_date(self, date):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    'SELECT * FROM daily_quests WHERE assigned_date=? ORDER BY is_completed, is_required DESC, id DESC',
                    (date,),
                ).fetchall()
            ]

    def list_between(self, start_date, end_date):
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    'SELECT * FROM daily_quests WHERE assigned_date BETWEEN ? AND ? '
                    'ORDER BY assigned_date ASC, is_completed, is_required DESC, id DESC',
                    (start_date, end_date),
                ).fetchall()
            ]

    def get(self, quest_id):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM daily_quests WHERE id=?', (int(quest_id),)).fetchone()
            return dict(row) if row else None

    def create(self, title, description, difficulty, points, category, is_required, assigned_date, is_recurring=0):
        now = now_str()
        with self.db.tx() as conn:
            cur = conn.execute(
                'INSERT INTO daily_quests(title,description,difficulty,points,category,is_required,is_recurring,is_completed,assigned_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (title, description, difficulty, points, category, int(is_required), int(is_recurring), 0, assigned_date, now, now),
            )
            return cur.lastrowid

    def update(self, quest_id, title, description, difficulty, points, category, is_required, is_recurring=0):
        with self.db.tx() as conn:
            conn.execute(
                'UPDATE daily_quests SET title=?,description=?,difficulty=?,points=?,category=?,is_required=?,is_recurring=?,updated_at=? WHERE id=?',
                (title, description, difficulty, points, category, int(is_required), int(is_recurring), now_str(), quest_id),
            )

    def set_completed(self, quest_id, completed):
        with self.db.tx() as conn:
            q = conn.execute('SELECT * FROM daily_quests WHERE id=?', (quest_id,)).fetchone()
            if not q:
                raise ValueError('委托不存在')
            if not completed and float(q['banked_points'] or 0) > 0:
                raise ValueError('该委托已入池，MVP阶段不可取消完成')
            conn.execute(
                'UPDATE daily_quests SET is_completed=?, completed_at=?, updated_at=? WHERE id=?',
                (int(completed), now_str() if completed else None, now_str(), quest_id),
            )

    def batch_set_completed(self, quest_ids, conn=None):
        ids = list(dict.fromkeys(int(qid) for qid in quest_ids))
        placeholders = ','.join('?' for _ in ids)
        own = conn is None
        conn = conn or self.db.connect()
        try:
            rows = conn.execute(
                f'SELECT id FROM daily_quests WHERE id IN ({placeholders})', ids
            ).fetchall()
            found = {int(row['id']) for row in rows}
            missing = [qid for qid in ids if qid not in found]
            if missing:
                raise ValueError('部分委托不存在或已经被处理，请刷新后重试')
            now = now_str()
            conn.execute(
                f'UPDATE daily_quests SET is_completed=1, completed_at=COALESCE(completed_at, ?), updated_at=? WHERE id IN ({placeholders})',
                [now, now, *ids],
            )
            if own:
                conn.commit()
        except Exception:
            if own:
                conn.rollback()
            raise
        finally:
            if own:
                conn.close()
        return ids

    def archive_and_delete(self, quest_id, reason, settlement_date=None, conn=None):
        own = conn is None
        conn = conn or self.db.connect()
        try:
            q = conn.execute('SELECT * FROM daily_quests WHERE id=?', (quest_id,)).fetchone()
            if not q:
                return
            sql = (
                'INSERT INTO quest_history(original_quest_id,title,description,difficulty,points,category,is_required,assigned_date,completed_at,archived_at,archive_reason,settlement_date) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)'
            )
            conn.execute(
                sql,
                (
                    q['id'],
                    q['title'],
                    q['description'],
                    q['difficulty'],
                    q['points'],
                    q['category'],
                    q['is_required'],
                    q['assigned_date'],
                    q['completed_at'],
                    now_str(),
                    reason,
                    settlement_date,
                ),
            )
            conn.execute('DELETE FROM daily_quests WHERE id=?', (quest_id,))
            if own:
                conn.commit()
        finally:
            if own:
                conn.close()

    def carry_over(self, quest_id, new_date, conn=None):
        own = conn is None
        conn = conn or self.db.connect()
        try:
            conn.execute('UPDATE daily_quests SET assigned_date=?, updated_at=? WHERE id=?', (new_date, now_str(), quest_id))
            if own:
                conn.commit()
        finally:
            if own:
                conn.close()

    def clone_for_next_day(self, quest, new_date, conn):
        now = now_str()
        cur = conn.execute(
            'INSERT INTO daily_quests(title,description,difficulty,points,category,is_required,is_recurring,is_completed,assigned_date,completed_at,banked_points,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                quest['title'],
                quest['description'],
                quest['difficulty'],
                quest['points'],
                quest['category'],
                int(quest['is_required'] or 0),
                1,
                0,
                new_date,
                None,
                0,
                now,
                now,
            ),
        )
        return cur.lastrowid

    def mark_completed_banked(self, date, conn):
        rows = conn.execute('SELECT * FROM daily_quests WHERE assigned_date=? AND is_completed=1', (date,)).fetchall()
        for r in rows:
            conn.execute('UPDATE daily_quests SET banked_points=? WHERE id=?', (r['points'], r['id']))

    def delete(self, quest_id):
        with self.db.tx() as conn:
            self.archive_and_delete(quest_id, 'deleted', None, conn)

    def batch_delete(self, quest_ids, conn=None):
        ids = list(dict.fromkeys(int(qid) for qid in quest_ids))
        placeholders = ','.join('?' for _ in ids)
        own = conn is None
        conn = conn or self.db.connect()
        try:
            rows = conn.execute(
                f'SELECT id FROM daily_quests WHERE id IN ({placeholders})', ids
            ).fetchall()
            found = {int(row['id']) for row in rows}
            missing = [qid for qid in ids if qid not in found]
            if missing:
                raise ValueError('部分委托不存在或已经被处理，请刷新后重试')
            for qid in ids:
                self.archive_and_delete(qid, 'batch_deleted', None, conn)
            if own:
                conn.commit()
        except Exception:
            if own:
                conn.rollback()
            raise
        finally:
            if own:
                conn.close()
        return ids
