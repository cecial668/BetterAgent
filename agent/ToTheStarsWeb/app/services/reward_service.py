from app.repositories.reward_repo import RewardRepo
from app.repositories.log_repo import LogRepo
from app.services.wallet_service import WalletService
from app.core.date_utils import today_str, now_str


class RewardService:
    def __init__(self, db):
        self.db = db
        self.repo = RewardRepo(db)
        self.wallet = WalletService(db)
        self.log = LogRepo(db)

    def list(self):
        rewards = self.repo.list_all()
        wallet = self.wallet.get()

        def group(r):
            if int(r['stock']) <= 0 or r['status'] == 'sold_out':
                return 2
            bal = wallet['practice_points'] if r['point_type'] == 'practice' else wallet['growth_points']
            return 0 if bal >= r['price'] else 1

        return sorted(rewards, key=lambda r: (group(r), r['price'], r['id']))

    def create(self, name, content, point_type, price, stock):
        if not name.strip():
            raise ValueError('奖励名称不能为空')
        if float(price) <= 0 or int(stock) < 0:
            raise ValueError('价格或库存非法')
        self.repo.create(name, content, point_type, float(price), int(stock))
        self.log.log('create', 'reward', None, {'name': name})

    def purchase(self, rid):
        with self.db.tx() as conn:
            r = self.repo.get(rid, conn)
            if not r or r['status'] != 'active' or int(r['stock']) <= 0:
                raise ValueError('该奖励已售空，无法购买')
            bal = self.wallet.spend(r['point_type'], r['price'], today_str(), 'reward_purchase', 'reward', rid, r['name'], conn)
            stock = self.repo.decrease_stock(rid, conn)
            self.repo.purchase_record(rid, r['name'], r.get('content') or '', r['point_type'], r['price'], stock, bal, conn)
            self.log.log('purchase', 'reward', rid, {'name': r['name'], 'price': r['price'], 'outbound_status': 'pending'}, conn)

    def list_purchases(self):
        return self.repo.list_purchases()

    def confirm_outbound(self, purchase_id):
        with self.db.tx() as conn:
            p = self.repo.get_purchase(purchase_id, conn)
            if not p:
                raise ValueError('购买记录不存在')
            if (p.get('outbound_status') or 'pending') == 'shipped':
                raise ValueError('该奖励已经出库')
            self.repo.mark_outbound(purchase_id, conn)
            self.log.log('reward_outbound', 'reward_purchase', purchase_id, {'reward_id': p.get('reward_id')}, conn)

    def delete(self, rid):
        self.repo.delete(rid)
        self.log.log('delete', 'reward', rid, {})

    def update(self, rid, name, content, point_type, price, stock):
        if not name.strip():
            raise ValueError('奖励名称不能为空')
        if float(price) <= 0 or int(stock) < 0:
            raise ValueError('价格或库存非法')
        status = 'sold_out' if int(stock) <= 0 else 'active'
        with self.db.tx() as conn:
            conn.execute(
                'UPDATE rewards SET name=?, content=?, point_type=?, price=?, stock=?, status=?, updated_at=? WHERE id=?',
                (name, content, point_type, float(price), int(stock), status, now_str(), rid),
            )
            self.log.log('update', 'reward', rid, {'name': name}, conn)
