from fastapi import APIRouter, Request
from app.api.schemas import VacationRange
from app.api.routes_common import db, raise400
from app.services.vacation_service import VacationService

router = APIRouter(prefix='/vacations')

@router.get('')
def list_vacations(request: Request): return VacationService(db(request)).list_all()

@router.post('/range')
def set_range(payload: VacationRange, request: Request):
    raise400(VacationService(db(request)).set_range, payload.start_date, payload.end_date, payload.reason)
    return {'ok': True, 'vacations': VacationService(db(request)).list_all()}

@router.post('/{date}/cancel')
def cancel(date: str, request: Request):
    raise400(VacationService(db(request)).cancel, date)
    return {'ok': True, 'vacations': VacationService(db(request)).list_all()}
