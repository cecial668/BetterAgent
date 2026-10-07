from app.core.date_utils import now_str
class LegendRepo:
    def __init__(self, db): self.db=db
    def list_all(self):
        with self.db.connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM legend_quests ORDER BY status, deadline, id DESC').fetchall()]
    def create(self,title,content,difficulty,growth_points,deadline,indicators):
        now=now_str()
        with self.db.tx() as conn:
            cur=conn.execute('INSERT INTO legend_quests(title,content,difficulty,growth_points,status,deadline,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(title,content,difficulty,growth_points,'active',deadline,now,now))
            lid=cur.lastrowid
            for t in indicators:
                if t.strip(): conn.execute('INSERT INTO legend_indicators(legend_id,title,description,is_completed,created_at,updated_at) VALUES(?,?,?,?,?,?)',(lid,t.strip(),'',0,now,now))
            return lid
    def delete(self, legend_id):
        with self.db.tx() as conn: conn.execute('DELETE FROM legend_quests WHERE id=?',(legend_id,))
    def indicators(self, legend_id):
        with self.db.connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM legend_indicators WHERE legend_id=? ORDER BY id',(legend_id,)).fetchall()]
    def add_indicator(self, legend_id, title):
        with self.db.tx() as conn: conn.execute('INSERT INTO legend_indicators(legend_id,title,description,is_completed,created_at,updated_at) VALUES(?,?,?,?,?,?)',(legend_id,title,'',0,now_str(),now_str()))
    def get_indicator(self, indicator_id):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM legend_indicators WHERE id=?', (int(indicator_id),)).fetchone()
        return dict(row) if row else None
    def complete_indicator(self, indicator_id, completed=True, conn=None):
        own=conn is None; conn=conn or self.db.connect()
        try:
            result=conn.execute('UPDATE legend_indicators SET is_completed=?, completed_at=?, updated_at=? WHERE id=?',(int(completed), now_str() if completed else None, now_str(), indicator_id))
            if not result.rowcount: raise ValueError('未找到该传说任务指标')
            if own: conn.commit()
        finally:
            if own: conn.close()
    def get(self, legend_id, conn):
        return conn.execute('SELECT * FROM legend_quests WHERE id=?',(legend_id,)).fetchone()
    def get_legend_by_indicator(self, indicator_id, conn):
        return conn.execute('SELECT l.* FROM legend_quests l JOIN legend_indicators i ON i.legend_id=l.id WHERE i.id=?',(indicator_id,)).fetchone()
    def all_indicators_done(self, legend_id, conn):
        rows=conn.execute('SELECT is_completed FROM legend_indicators WHERE legend_id=?',(legend_id,)).fetchall()
        return bool(rows) and all(r['is_completed'] for r in rows)
    def mark_completed(self, legend_id, conn):
        now=now_str()
        result=conn.execute("""UPDATE legend_quests
                             SET status='completed', completed_at=?, points_awarded=1, updated_at=?
                             WHERE id=? AND points_awarded=0 AND status='active'""",(now,now,legend_id))
        return bool(result.rowcount)
