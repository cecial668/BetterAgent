from fastapi import APIRouter, Query, Request

from app.api.routes_common import actor_of, db, raise400
from app.api.schemas import SchedulePlanCreate, SchedulePlanUpdate
from app.services.audit_service import AuditService
from app.services.schedule_service import ScheduleService

router = APIRouter(prefix='/schedule')


@router.get('/week')
def week(request: Request, date: str | None = Query(default=None)):
    return raise400(ScheduleService(db(request)).week, date)


@router.get('/day')
def day(request: Request, date: str | None = Query(default=None)):
    return raise400(ScheduleService(db(request)).day, date)


@router.post('/plans')
def create_plan(payload: SchedulePlanCreate, request: Request):
    plan = raise400(ScheduleService(db(request)).create, payload)
    AuditService(db(request)).record(
        actor=actor_of(request), action='schedule.create', target_type='schedule_plan', target_id=plan['id'],
        params=payload.model_dump(), result={'id': plan['id'], 'date': plan['plan_date']},
        undo_payload={'plan_id': plan['id']}, undoable=True,
    )
    return {'ok': True, 'plan': plan, 'date': plan['plan_date']}


@router.put('/plans/{plan_id}')
def update_plan(plan_id: int, payload: SchedulePlanUpdate, request: Request):
    audit = AuditService(db(request)); before = audit.snapshot_plan(plan_id)
    plan = raise400(ScheduleService(db(request)).update, plan_id, payload)
    audit.record(
        actor=actor_of(request), action='schedule.update', target_type='schedule_plan', target_id=plan_id,
        params=payload.model_dump(), result={'id': plan['id'], 'date': plan['plan_date']},
        undo_payload={'plan_id': plan_id, 'before': before}, undoable=bool(before),
    )
    return {'ok': True, 'plan': plan, 'date': plan['plan_date']}


@router.delete('/plans/{plan_id}')
def delete_plan(plan_id: int, request: Request):
    audit = AuditService(db(request)); snapshot = audit.snapshot_plan(plan_id)
    raise400(ScheduleService(db(request)).delete, plan_id)
    audit.record(
        actor=actor_of(request), action='schedule.delete', target_type='schedule_plan', target_id=plan_id,
        result={'ok': True}, undo_payload={'snapshot': snapshot}, undoable=bool(snapshot),
    )
    return {'ok': True}
