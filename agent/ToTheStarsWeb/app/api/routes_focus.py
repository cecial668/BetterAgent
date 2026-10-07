from fastapi import APIRouter, Request, Query

from app.api.routes_common import db, raise400
from app.api.schemas import FocusSessionCreate
from app.services.focus_service import FocusService

router = APIRouter(prefix='/focus')


@router.get('/today')
def today(request: Request):
    return FocusService(db(request)).today()


@router.post('/sessions')
def create_session(payload: FocusSessionCreate, request: Request):
    return raise400(FocusService(db(request)).create_session, payload)


@router.get('/sessions')
def sessions(request: Request, date: str | None = None, limit: int = Query(default=100, ge=1, le=500)):
    return FocusService(db(request)).sessions(date=date, limit=limit)


@router.get('/summary')
def summary(request: Request, days: int = Query(default=14, ge=1, le=366)):
    return FocusService(db(request)).summary(days=days)
