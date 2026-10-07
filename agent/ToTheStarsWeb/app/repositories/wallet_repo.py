from app.core.date_utils import now_str
class WalletRepo:
    def __init__(self, db): self.db=db
    def get(self):
        with self.db.connect() as conn:
            return dict(conn.execute('SELECT * FROM point_wallet WHERE id=1').fetchone())
    def add(self, point_type, amount, date, reason, related_type='', related_id=None, note='', conn=None):
        own=conn is None; conn=conn or self.db.connect()
        try:
            col='practice_points' if point_type=='practice' else 'growth_points'
            row=conn.execute(f'SELECT {col} FROM point_wallet WHERE id=1').fetchone()
            balance=float(row[col])+float(amount)
            if balance < -1e-9: raise ValueError('点数不足')
            conn.execute(f'UPDATE point_wallet SET {col}=?, updated_at=? WHERE id=1',(balance,now_str()))
            conn.execute('INSERT INTO point_transactions(date,created_at,point_type,amount,reason,related_type,related_id,balance_after,note) VALUES(?,?,?,?,?,?,?,?,?)',
                         (date,now_str(),point_type,amount,reason,related_type,related_id,balance,note))
            if own: conn.commit()
            return balance
        finally:
            if own: conn.close()
    def transactions(self, limit=200):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM point_transactions ORDER BY id DESC LIMIT ?', (limit,)).fetchall()]
