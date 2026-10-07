from app.core.constants import LEGEND_META
from app.repositories.legend_repo import LegendRepo
from app.repositories.log_repo import LogRepo
from app.services.wallet_service import WalletService
from app.core.date_utils import today_str
class LegendService:
    def __init__(self, db): self.db=db; self.repo=LegendRepo(db); self.wallet=WalletService(db); self.log=LogRepo(db)
    def list(self): return self.repo.list_all()
    def indicators(self,lid): return self.repo.indicators(lid)
    def create(self,title,content,difficulty,deadline,indicators):
        if not title.strip(): raise ValueError('传说任务名称不能为空')
        if not any(i.strip() for i in indicators): raise ValueError('至少需要一个任务指标')
        points=LEGEND_META[difficulty]['points']; lid=self.repo.create(title,content,difficulty,points,deadline,indicators)
        self.log.log('create','legend_quest',lid,{'title':title}); return lid
    def add_indicator(self,lid,title): self.repo.add_indicator(lid,title); self.log.log('create','legend_indicator',lid,{'title':title})
    def complete_indicator(self,iid,completed=True):
        with self.db.tx() as conn:
            legend=self.repo.get_legend_by_indicator(iid,conn)
            if not legend: raise ValueError('未找到该传说任务指标')
            if legend['status'] != 'active' or legend['points_awarded']:
                raise ValueError('已完成或已归档的传说任务不能修改指标')
            self.repo.complete_indicator(iid,completed,conn)
            self.log.log('toggle_indicator','legend_indicator',iid,{'completed':completed},conn)
    def confirm_complete(self,lid):
        with self.db.tx() as conn:
            legend=self.repo.get(lid,conn)
            if not legend: raise ValueError('未找到该传说任务')
            if legend['points_awarded'] or legend['status'] == 'completed':
                return False
            if legend['status'] != 'active': raise ValueError('该传说任务当前不能完成')
            if not self.repo.all_indicators_done(lid,conn):
                raise ValueError('所有分指标完成后才能确认传说任务')
            if not self.repo.mark_completed(lid,conn): return False
            self.wallet.add_growth(legend['growth_points'], today_str(), 'legend_complete','legend_quest',legend['id'],'传说任务完成',conn)
            self.log.log('confirm_complete','legend_quest',lid,{'growth_points':legend['growth_points']},conn)
            return True
    def delete(self,lid): self.repo.delete(lid); self.log.log('delete','legend_quest',lid,{})

# Web MVP 扩展：基础信息编辑与归档删除

def _legend_update(self, lid, title, content, difficulty, deadline):
    from app.core.constants import LEGEND_META
    from app.core.date_utils import now_str
    points = LEGEND_META[difficulty]['points']
    with self.db.tx() as conn:
        conn.execute('UPDATE legend_quests SET title=?, content=?, difficulty=?, growth_points=?, deadline=?, updated_at=? WHERE id=?',
                     (title, content, difficulty, points, deadline, now_str(), lid))
        self.log.log('update','legend_quest',lid,{'title':title},conn)

def _legend_archive(self, lid):
    from app.core.date_utils import now_str
    with self.db.tx() as conn:
        conn.execute("UPDATE legend_quests SET status='archived', updated_at=? WHERE id=?", (now_str(), lid))
        self.log.log('archive','legend_quest',lid,{},conn)

LegendService.update = _legend_update
LegendService.delete = _legend_archive
