from app.repositories.settlement_repo import SettlementRepo
from app.repositories.wallet_repo import WalletRepo
from app.repositories.state_repo import StateRepo


class StatsService:
    def __init__(self, db):
        self.db = db
        self.settlement_repo = SettlementRepo(db)
        self.wallet = WalletRepo(db)
        self.state_repo = StateRepo(db)

    def completion_rate(self):
        rows = self.settlement_repo.list_recent(1000)
        normal = [r for r in rows if not r['is_vacation']]
        done = [r for r in normal if r['is_success']]
        return (len(done), len(normal), (len(done) / len(normal) * 100 if normal else 0))

    def settlements(self):
        return self.settlement_repo.list_recent()

    def transactions(self):
        return self.wallet.transactions()

    def states(self):
        return self.state_repo.list_recent()
