from app.core.date_utils import now_str
class VacationRepo:
    def __init__(self, db): self.db=db
    def is_vacation(self, date):
        with self.db.connect() as conn:
            return bool(conn.execute('SELECT 1 FROM vacation_days WHERE date=? AND is_active=1',(date,)).fetchone())
    def set_day(self, date, reason=''):
        with self.db.tx() as conn:
            conn.execute('INSERT INTO vacation_days(date,reason,is_active,created_at,canceled_at) VALUES(?,?,?,?,NULL) ON CONFLICT(date) DO UPDATE SET reason=excluded.reason,is_active=1,canceled_at=NULL',(date,reason,1,now_str()))
    def cancel(self, date):
        with self.db.tx() as conn: conn.execute('UPDATE vacation_days SET is_active=0,canceled_at=? WHERE date=?',(now_str(),date))
    def list_all(self):
        with self.db.connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM vacation_days ORDER BY date DESC LIMIT 200').fetchall()]
