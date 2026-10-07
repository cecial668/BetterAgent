from fastapi import APIRouter, Request
from app.api.schemas import RewardCreate, RewardUpdate
from app.api.routes_common import db, raise400, format_reward, format_reward_purchase
from app.services.reward_service import RewardService
from app.services.wallet_service import WalletService

router = APIRouter(prefix='/rewards')


@router.get('')
def list_rewards(request: Request):
    wallet = WalletService(db(request)).get()
    return [format_reward(r, wallet) for r in RewardService(db(request)).list()]


@router.get('/purchases')
def list_reward_purchases(request: Request):
    return [format_reward_purchase(p) for p in RewardService(db(request)).list_purchases()]


@router.post('/purchases/{purchase_id}/outbound')
def confirm_reward_outbound(purchase_id: int, request: Request):
    raise400(RewardService(db(request)).confirm_outbound, purchase_id)
    return {'ok': True, 'purchases': [format_reward_purchase(p) for p in RewardService(db(request)).list_purchases()]}


@router.post('')
def create_reward(payload: RewardCreate, request: Request):
    raise400(RewardService(db(request)).create, payload.name, payload.content, payload.point_type, payload.price, payload.stock)
    return {'ok': True}


@router.put('/{rid}')
def update_reward(rid: int, payload: RewardUpdate, request: Request):
    raise400(RewardService(db(request)).update, rid, payload.name, payload.content, payload.point_type, payload.price, payload.stock)
    return {'ok': True}


@router.delete('/{rid}')
def delete_reward(rid: int, request: Request):
    raise400(RewardService(db(request)).delete, rid)
    return {'ok': True}


@router.post('/{rid}/purchase')
def purchase_reward(rid: int, request: Request):
    raise400(RewardService(db(request)).purchase, rid)
    wallet = WalletService(db(request)).get()
    return {'ok': True, 'wallet': wallet, 'rewards': [format_reward(r, wallet) for r in RewardService(db(request)).list()]}
