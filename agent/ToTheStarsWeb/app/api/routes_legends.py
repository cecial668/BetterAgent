from fastapi import APIRouter, Request, Query
from app.api.schemas import LegendCreate, LegendUpdate, IndicatorCreate, CompleteRequest
from app.api.routes_common import actor_of, db, raise400, format_legend
from app.repositories.legend_repo import LegendRepo
from app.services.audit_service import AuditService
from app.services.legend_service import LegendService
from app.services.wallet_service import WalletService

router = APIRouter(prefix='/legends')

def all_legends(request, status=None):
    svc=LegendService(db(request)); out=[]
    for l in svc.list():
        if status:
            if l.get('status') != status: continue
        elif l.get('status') == 'archived':
            continue
        out.append(format_legend(l, svc.indicators(l['id'])))
    return out

@router.get('')
def list_legends(request: Request, status: str | None = Query(default=None)):
    return all_legends(request, status)

@router.post('')
def create_legend(payload: LegendCreate, request: Request):
    lid=raise400(LegendService(db(request)).create, payload.title, payload.content, payload.difficulty, payload.deadline, payload.indicators)
    AuditService(db(request)).record(
        actor=actor_of(request), action='legend.create', target_type='legend_quest', target_id=lid,
        params=payload.model_dump(), result={'id': lid},
    )
    return {'ok': True, 'id': lid}

@router.put('/{lid}')
def update_legend(lid: int, payload: LegendUpdate, request: Request):
    raise400(LegendService(db(request)).update, lid, payload.title, payload.content, payload.difficulty, payload.deadline)
    AuditService(db(request)).record(
        actor=actor_of(request), action='legend.update', target_type='legend_quest', target_id=lid,
        params=payload.model_dump(), result={'ok': True},
    )
    return {'ok': True}

@router.delete('/{lid}')
def delete_legend(lid: int, request: Request):
    raise400(LegendService(db(request)).delete, lid)
    AuditService(db(request)).record(
        actor=actor_of(request), action='legend.delete', target_type='legend_quest', target_id=lid,
        result={'ok': True},
    )
    return {'ok': True}

@router.post('/{lid}/indicators')
def add_indicator(lid: int, payload: IndicatorCreate, request: Request):
    raise400(LegendService(db(request)).add_indicator, lid, payload.title)
    AuditService(db(request)).record(
        actor=actor_of(request), action='legend.indicator.add', target_type='legend_quest', target_id=lid,
        params={'title': payload.title}, result={'ok': True},
    )
    return {'ok': True}

@router.post('/{lid}/complete')
def complete_legend(lid: int, request: Request):
    completed=raise400(LegendService(db(request)).confirm_complete, lid)
    AuditService(db(request)).record(
        actor=actor_of(request), action='legend.complete', target_type='legend_quest', target_id=lid,
        result={'completed': completed},
    )
    return {'ok': True, 'completed': completed, 'wallet': WalletService(db(request)).get(), 'legends': all_legends(request)}

@router.post('/indicators/{iid}/complete')
def complete_indicator(iid: int, payload: CompleteRequest, request: Request):
    audit=AuditService(db(request)); indicator=LegendRepo(db(request)).get_indicator(iid)
    raise400(LegendService(db(request)).complete_indicator, iid, payload.completed)
    previous = bool(indicator.get('is_completed')) if indicator else None
    if previous is not None:
        audit.record(
            actor=actor_of(request), action='legend.indicator.complete', target_type='legend_indicator', target_id=iid,
            params={'completed': payload.completed}, result={'ok': True},
            undo_payload={'indicator_id': iid, 'completed': previous}, undoable=True,
        )
    return {'ok': True, 'wallet': WalletService(db(request)).get(), 'legends': all_legends(request)}
