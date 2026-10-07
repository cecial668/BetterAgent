import json
from app.core.date_utils import now_str
class SettlementRepo:
    def __init__(self, db): self.db=db
    def exists(self, date):
        with self.db.connect() as conn: return bool(conn.execute('SELECT 1 FROM daily_settlements WHERE date=?',(date,)).fetchone())
    def upsert(self, result, conn=None):
        own=conn is None; conn=conn or self.db.connect()
        try:
            sql=('INSERT INTO daily_settlements(date,is_vacation,is_success,day_title,total_points,points_banked,state_bonus,required_all_done,completed_count,total_count,settled_at,summary_json) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET is_vacation=excluded.is_vacation,is_success=excluded.is_success,day_title=excluded.day_title,total_points=excluded.total_points,points_banked=excluded.points_banked,state_bonus=excluded.state_bonus,required_all_done=excluded.required_all_done,completed_count=excluded.completed_count,total_count=excluded.total_count,settled_at=excluded.settled_at,summary_json=excluded.summary_json')
            conn.execute(sql,(result['date'], int(result['is_vacation']), None if result.get('is_success') is None else int(result['is_success']), result['day_title'], result['total_points'], result['points_banked'], result.get('state_bonus',0), int(result.get('required_all_done',False)), result.get('completed_count',0), result.get('total_count',0), now_str(), json.dumps(result, ensure_ascii=False, default=str)))
            if own: conn.commit()
        finally:
            if own: conn.close()
    def list_recent(self, limit=100):
        with self.db.connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM daily_settlements ORDER BY date DESC LIMIT ?',(limit,)).fetchall()]
