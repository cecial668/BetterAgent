from fastapi import APIRouter, Request
from app.core.config import DB_PATH
from app.core.constants import DIFFICULTY_META, LEGEND_META, DEFAULT_CATEGORIES, EMOTIONS, SOCIAL_TYPES
from app.core.date_utils import DAY_BOUNDARY_HOUR
from app.services.wallet_service import WalletService
from app.services.settlement_service import SettlementService
from app.api.schemas import DateRequest
from app.api.routes_common import db, today, raise400

router = APIRouter()


@router.get('/health')
def health():
    return {
        'ok': True,
        'app': '向着星',
        'version': 'web-mvp',
    }


@router.get('/constants')
def constants():
    return {
        'difficulties': DIFFICULTY_META,
        'legend_difficulties': LEGEND_META,
        'categories': DEFAULT_CATEGORIES,
        'emotions': EMOTIONS,
        'social_types': SOCIAL_TYPES,
        'point_types': {
            'practice': '历练点',
            'growth': '成长点',
        },
    }


@router.get('/wallet')
def wallet(request: Request):
    return WalletService(db(request)).get()


@router.get('/bootstrap')
def bootstrap(request: Request):
    from app.services.vacation_service import VacationService

    return {
        'date': today(),
        'wallet': WalletService(db(request)).get(),
        'constants': constants(),
        'is_vacation': VacationService(db(request)).is_vacation(today()),
        'startup_results': getattr(request.app.state, 'startup_results', []),
        'data_path': str(DB_PATH),
        'day_boundary_hour': DAY_BOUNDARY_HOUR,
    }


@router.get('/rollover-status')
def rollover_status(request: Request):
    """
    前端轮询接口。

    如果后端在线跨过凌晨 4 点，并已经自动完成前一天日终结算，
    这里会返回结算结果，然后清空待展示结果，避免前端重复弹窗。
    """
    results = list(getattr(request.app.state, 'rollover_results', []))
    request.app.state.rollover_results = []

    payload = {
        'date': today(),
        'day_boundary_hour': DAY_BOUNDARY_HOUR,
        'results': results,
    }
    if results:
        payload['wallet'] = WalletService(db(request)).get()
    return payload


@router.post('/shutdown')
def shutdown(request: Request):
    if getattr(request.app.state, 'session', None):
        request.app.state.session.close()
    return {'ok': True}


@router.post('/settlements/catch-up')
def catch_up(payload: DateRequest, request: Request):
    current = payload.date or today()
    last = getattr(request.app.state, 'last_session_date', None)
    return raise400(SettlementService(db(request)).catch_up, last, current)
