from fastapi import APIRouter, Request, Query
from app.api.schemas import QuestCreate, QuestUpdate, CompleteRequest, QuestBatchRequest
from app.api.routes_common import actor_of, db, today, raise400, format_quest, condition_for
from app.services.audit_service import AuditService
from app.services.daily_quest_service import DailyQuestService
from app.services.schedule_service import ScheduleService
from app.services.vacation_service import VacationService
from app.services.wallet_service import WalletService

router = APIRouter(prefix='/quests')

def today_payload(request: Request):
    d=today(); svc=DailyQuestService(db(request)); qs=[format_quest(q) for q in svc.list(d)]
    vac=VacationService(db(request)).is_vacation(d)
    return {'date': d, 'is_vacation': vac, 'wallet': WalletService(db(request)).get(),
            'condition': condition_for(qs, vac), 'quests': qs}

@router.get('/today')
def today_quests(request: Request):
    return today_payload(request)

@router.get('')
def list_quests(request: Request, date: str | None = Query(default=None)):
    return [format_quest(q) for q in DailyQuestService(db(request)).list(date or today())]

@router.post('')
def create_quest(payload: QuestCreate, request: Request):
    svc=DailyQuestService(db(request))
    qid=raise400(svc.create, payload.title, payload.description, payload.difficulty, payload.category, payload.is_required, payload.assigned_date, payload.is_recurring)
    AuditService(db(request)).record(
        actor=actor_of(request), action='quest.create', target_type='daily_quest', target_id=qid,
        params=payload.model_dump(), result={'id': qid},
        undo_payload={'quest_id': qid}, undoable=True,
    )
    return {'ok': True, 'id': qid, 'quest': next((format_quest(q) for q in svc.list(payload.assigned_date or today()) if q['id']==qid), None)}

@router.put('/{qid}')
def update_quest(qid: int, payload: QuestUpdate, request: Request):
    audit=AuditService(db(request)); before=audit.snapshot_quest(qid)
    svc=DailyQuestService(db(request)); raise400(svc.update, qid, payload.title, payload.description, payload.difficulty, payload.category, payload.is_required, payload.is_recurring)
    # 委托文案变更后同步刷新绑定在日程里的计划片段
    ScheduleService(db(request)).sync_quest(qid, payload.title, payload.description)
    audit.record(
        actor=actor_of(request), action='quest.update', target_type='daily_quest', target_id=qid,
        params=payload.model_dump(), result={'ok': True},
        undo_payload={'quest_id': qid, 'before': before}, undoable=bool(before),
    )
    return {'ok': True}

@router.post('/batch/complete')
def batch_complete_quests(payload: QuestBatchRequest, request: Request):
    completed = raise400(DailyQuestService(db(request)).batch_complete, payload.ids)
    AuditService(db(request)).record(
        actor=actor_of(request), action='quest.batch_complete', target_type='daily_quest',
        params={'ids': payload.ids}, result={'completed_ids': completed},
    )
    return {'ok': True, 'completed_ids': completed, **today_payload(request)}

@router.post('/batch/delete')
def batch_delete_quests(payload: QuestBatchRequest, request: Request):
    deleted = raise400(DailyQuestService(db(request)).batch_delete, payload.ids)
    ScheduleService(db(request)).unbind_quests(deleted)
    AuditService(db(request)).record(
        actor=actor_of(request), action='quest.batch_delete', target_type='daily_quest',
        params={'ids': payload.ids}, result={'deleted_ids': deleted},
    )
    return {'ok': True, 'deleted_ids': deleted, **today_payload(request)}

@router.post('/{qid}/complete')
def complete_quest(qid: int, payload: CompleteRequest, request: Request):
    audit=AuditService(db(request)); before=audit.snapshot_quest(qid)
    svc=DailyQuestService(db(request)); raise400(svc.set_completed, qid, payload.completed)
    previous_completed = bool(before.get('is_completed')) if before else (not payload.completed)
    audit.record(
        actor=actor_of(request), action='quest.complete', target_type='daily_quest', target_id=qid,
        params={'completed': payload.completed}, result={'completed': payload.completed},
        undo_payload={'quest_id': qid, 'completed': previous_completed}, undoable=True,
    )
    d=today(); qs=[format_quest(q) for q in svc.list(d)]; vac=VacationService(db(request)).is_vacation(d)
    return {'ok': True, 'condition': condition_for(qs, vac), 'quests': qs}

@router.delete('/{qid}')
def delete_quest(qid: int, request: Request):
    audit=AuditService(db(request)); snapshot=audit.snapshot_quest(qid)
    raise400(DailyQuestService(db(request)).delete, qid)
    # 委托被删除后保留计划内容，但解除绑定转为自定义计划
    ScheduleService(db(request)).unbind_quests([qid])
    audit.record(
        actor=actor_of(request), action='quest.delete', target_type='daily_quest', target_id=qid,
        result={'ok': True}, undo_payload={'snapshot': snapshot}, undoable=bool(snapshot),
    )
    return {'ok': True}
