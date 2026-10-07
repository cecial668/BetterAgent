from app.repositories.vacation_repo import VacationRepo
from app.repositories.log_repo import LogRepo
from app.core.date_utils import date_range
class VacationService:
    def __init__(self, db): self.repo=VacationRepo(db); self.log=LogRepo(db)
    def is_vacation(self,date): return self.repo.is_vacation(date)
    def set_range(self,start,end,reason=''):
        for d in date_range(start,end): self.repo.set_day(d,reason)
        self.log.log('set_vacation','vacation',None,{'start':start,'end':end,'reason':reason})
    def cancel(self,date): self.repo.cancel(date); self.log.log('cancel_vacation','vacation',None,{'date':date})
    def list_all(self): return self.repo.list_all()
