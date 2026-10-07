from app.repositories.quest_repo import QuestRepo
from app.repositories.schedule_repo import ScheduleRepo
from app.repositories.settlement_repo import SettlementRepo
from app.repositories.log_repo import LogRepo
from app.services.wallet_service import WalletService
from app.services.vacation_service import VacationService
from app.services.state_service import StateService
from app.core.date_utils import next_date, date_range, today_str, now_str

class SettlementService:
    def __init__(self, db):
        self.db=db; self.quest=QuestRepo(db); self.settlements=SettlementRepo(db)
        self.wallet=WalletService(db); self.vac=VacationService(db); self.state=StateService(db); self.log=LogRepo(db)
    def _title(self,total,is_vacation):
        if is_vacation: return '假期日'
        if total<=0: return '摆烂日'
        if total<4: return '休息日'
        if total==4: return '行动日'
        return '拓展日'
    def manual_settle(self,date=None):
        date=date or today_str()
        with self.db.tx() as conn:
            qs=[dict(r) for r in conn.execute('SELECT * FROM daily_quests WHERE assigned_date=?',(date,)).fetchall()]
            is_vac=self.vac.is_vacation(date)
            total=sum(float(q['points']) for q in qs if q['is_completed'])
            banked=sum(float(q['banked_points'] or 0) for q in qs if q['is_completed'])
            required_all=all(q['is_completed'] for q in qs if q['is_required'])
            can_bank=is_vac or (total>=4 and required_all)
            new=max(total-banked,0) if can_bank else 0
            if new>0:
                self.wallet.add_practice(new,date,'manual_settlement','daily_quest',None,'普通结算入池',conn)
                self.quest.mark_completed_banked(date,conn)
            self.log.log('manual_settle','settlement',None,{'date':date,'points':new},conn)
            return {'date':date,'can_bank':can_bank,'points_banked':new,'total_points':total,'required_all_done':required_all,'is_vacation':is_vac}
    def settle_day(self,date=None):
        date=date or today_str()
        if self.settlements.exists(date):
            return {'date':date,'already_settled':True,'day_title':'已结算','points_banked':0,'total_points':0,'completed_titles':[]}
        manual=self.manual_settle(date)
        with self.db.tx() as conn:
            qs=[dict(r) for r in conn.execute('SELECT * FROM daily_quests WHERE assigned_date=?',(date,)).fetchall()]
            is_vac=manual['is_vacation']; total=manual['total_points']; required_all=manual['required_all_done']
            is_success=None if is_vac else (total>=4 and required_all)
            day_title=self._title(total,is_vac)
            completed=[q for q in qs if q['is_completed']]
            carried=[q for q in qs if not q['is_completed']]
            state_bonus=self.state.grant_bonus_if_needed(date,conn)
            result={'date':date,'is_vacation':is_vac,'is_success':is_success,'day_title':day_title,'total_points':total,
                    'points_banked':manual['points_banked'],'state_bonus':state_bonus,'required_all_done':required_all,
                    'completed_count':len(completed),'total_count':len(qs),'completed_titles':[q['title'] for q in completed],
                    'carried_titles':[q['title'] for q in carried]}
            self.settlements.upsert(result,conn)
            tomorrow = next_date(date)
            for q in completed:
                if q.get('is_recurring'):
                    self.quest.clone_for_next_day(q, tomorrow, conn)
                self.quest.archive_and_delete(q['id'],'completed',date,conn)
            for q in carried: self.quest.carry_over(q['id'],tomorrow,conn)
            # 顺延的委托，其已排期计划一并移动到新日期，保持绑定一致
            if carried: ScheduleRepo(self.db).move_quest_plans([q['id'] for q in carried], tomorrow, conn)
            self.log.log('end_settle','settlement',None,result,conn)
            return result
    def create_absent_settlement(self,date):
        is_vac=self.vac.is_vacation(date)
        result={'date':date,'is_vacation':is_vac,'is_success':None if is_vac else False,'day_title':'假期日' if is_vac else '摆烂日','total_points':0,'points_banked':0,'state_bonus':0,'required_all_done':False,'completed_count':0,'total_count':0,'completed_titles':[],'carried_titles':[]}
        self.settlements.upsert(result)
        return result
    def repair_stranded_quests(self,current_date=None):
        current_date=current_date or today_str()
        with self.db.tx() as conn:
            rows=conn.execute('''SELECT q.id FROM daily_quests q
                                 INNER JOIN daily_settlements s ON s.date=q.assigned_date
                                 WHERE q.is_completed=0 AND q.assigned_date<?''',(current_date,)).fetchall()
            if rows:
                conn.executemany('UPDATE daily_quests SET assigned_date=?, updated_at=? WHERE id=?',
                                 [(current_date, now_str(), r['id']) for r in rows])
                ScheduleRepo(self.db).move_quest_plans([r['id'] for r in rows], current_date, conn)
            return len(rows)
    def catch_up(self,last_date,current_date=None):
        current_date=current_date or today_str()
        if not last_date or last_date>=current_date: return []
        results=[]
        self.repair_stranded_quests(current_date)
        for d in date_range(last_date, current_date):
            if d==current_date: break
            if not self.settlements.exists(d): results.append(self.settle_day(d))
        self.repair_stranded_quests(current_date)
        return results
