from fastapi import APIRouter, Request, Query
from app.api.schemas import DateRequest
from app.api.routes_common import db, today, raise400, explain_condition
from app.services.settlement_service import SettlementService
from app.services.wallet_service import WalletService

router = APIRouter(prefix='/settlements')

@router.post('/manual')
def manual(payload: DateRequest, request: Request):
    result = raise400(SettlementService(db(request)).manual_settle, payload.date or today())
    result['wallet'] = WalletService(db(request)).get()
    result['explain'] = '本次新增入池 %.1f 点。' % result['points_banked'] if result['can_bank'] else explain_condition(result['total_points'], result['required_all_done'], result['is_vacation'], False)
    return result

@router.post('/end')
def end(payload: DateRequest, request: Request):
    result = raise400(SettlementService(db(request)).settle_day, payload.date or today())
    result['wallet'] = WalletService(db(request)).get()
    if result.get('already_settled'):
        result['explain']='该日期已经完成日终结算，不会重复发放点数。'
    else:
        state_bonus=result.get('state_bonus',0)
        result['explain']=f"{result.get('day_title','')}结算完成：新入池 {result.get('points_banked',0):g} 点，状态奖励 {state_bonus:g} 点。"
    return result

@router.get('/recent')
def recent(request: Request, limit: int = Query(default=30, ge=1, le=500)):
    return SettlementService(db(request)).settlements.list_recent(limit)
