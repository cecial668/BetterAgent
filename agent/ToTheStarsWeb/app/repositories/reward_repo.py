from app.core.date_utils import now_str


class RewardRepo:
    def __init__(self, db):
        self.db = db

    def list_all(self):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM rewards WHERE status<>'archived' ORDER BY id DESC").fetchall()]

    def create(self, name, content, point_type, price, stock):
        with self.db.tx() as conn:
            conn.execute(
                'INSERT INTO rewards(name,content,point_type,price,stock,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (name, content, point_type, price, stock, 'active', now_str(), now_str()),
            )

    def delete(self, reward_id):
        with self.db.tx() as conn:
            conn.execute("UPDATE rewards SET status='archived', updated_at=? WHERE id=?", (now_str(), reward_id))

    def get(self, reward_id, conn=None):
        own = conn is None
        conn = conn or self.db.connect()
        try:
            r = conn.execute('SELECT * FROM rewards WHERE id=?', (reward_id,)).fetchone()
            return dict(r) if r else None
        finally:
            if own:
                conn.close()

    def decrease_stock(self, reward_id, conn):
        r = conn.execute('SELECT stock FROM rewards WHERE id=?', (reward_id,)).fetchone()
        stock = int(r['stock']) - 1
        status = 'sold_out' if stock <= 0 else 'active'
        conn.execute('UPDATE rewards SET stock=?, status=?, updated_at=? WHERE id=?', (stock, status, now_str(), reward_id))
        return stock

    def purchase_record(self, reward_id, reward_name, reward_content, point_type, price, stock_after, balance_after, conn):
        conn.execute(
            'INSERT INTO reward_purchases(reward_id,reward_name,reward_content,purchased_at,point_type,price,stock_after,balance_after,outbound_status,outbound_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (reward_id, reward_name, reward_content, now_str(), point_type, price, stock_after, balance_after, 'pending', None),
        )

    def list_purchases(self):
        sql = """
            SELECT
                p.*,
                COALESCE(NULLIF(p.reward_name, ''), r.name, '已删除奖励') AS display_name,
                COALESCE(NULLIF(p.reward_content, ''), r.content, '') AS display_content,
                r.status AS reward_status
            FROM reward_purchases p
            LEFT JOIN rewards r ON r.id = p.reward_id
            ORDER BY CASE COALESCE(p.outbound_status, 'pending') WHEN 'pending' THEN 0 ELSE 1 END,
                     p.purchased_at DESC,
                     p.id DESC
        """
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def get_purchase(self, purchase_id, conn=None):
        own = conn is None
        conn = conn or self.db.connect()
        try:
            r = conn.execute('SELECT * FROM reward_purchases WHERE id=?', (purchase_id,)).fetchone()
            return dict(r) if r else None
        finally:
            if own:
                conn.close()

    def mark_outbound(self, purchase_id, conn):
        conn.execute(
            "UPDATE reward_purchases SET outbound_status='shipped', outbound_at=? WHERE id=?",
            (now_str(), purchase_id),
        )
