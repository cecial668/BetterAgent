from app.repositories.state_repo import StateRepo
from app.repositories.log_repo import LogRepo
from app.services.wallet_service import WalletService
from app.core.date_utils import today_str
class StateService:
    def __init__(self, db): self.repo=StateRepo(db); self.wallet=WalletService(db); self.log=LogRepo(db)
    def save(self,journal_title,rating,emotions,social_type,social_feeling,energy,review_text,date=None):
        journal_title=(journal_title or '').strip()
        if not journal_title: raise ValueError('请为今天的日记写一个标题')
        if len(journal_title)>20: raise ValueError('日记标题不能超过 20 个字')
        self.repo.save(date or today_str(),journal_title,rating,emotions,social_type,social_feeling,energy,review_text)
        self.log.log('save','daily_state',None,{'date':date or today_str()})
    def get(self,date=None): return self.repo.get(date or today_str())
    def list_recent(self): return self.repo.list_recent()
    def grant_bonus_if_needed(self,date,conn):
        state=self.repo.get(date)
        if not state or state['reward_granted']: return 0.0
        self.wallet.add_practice(0.5,date,'state_bonus','daily_state',None,'每日状态记录奖励',conn)
        self.repo.mark_reward(date,conn)
        return 0.5
