from app.repositories.wallet_repo import WalletRepo
class WalletService:
    def __init__(self, db): self.repo=WalletRepo(db); self.db=db
    def get(self): return self.repo.get()
    def add_practice(self, amount, date, reason, related_type='', related_id=None, note='', conn=None):
        return self.repo.add('practice', amount, date, reason, related_type, related_id, note, conn)
    def add_growth(self, amount, date, reason, related_type='', related_id=None, note='', conn=None):
        return self.repo.add('growth', amount, date, reason, related_type, related_id, note, conn)
    def spend(self, point_type, amount, date, reason, related_type='', related_id=None, note='', conn=None):
        return self.repo.add(point_type, -abs(float(amount)), date, reason, related_type, related_id, note, conn)
    def transactions(self): return self.repo.transactions()
