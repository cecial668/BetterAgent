from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Request, Query, UploadFile, File, HTTPException
from app.api.schemas import StateSave, ImageOrder
from app.api.routes_common import actor_of, db, today, raise400, safe_json
from app.services.audit_service import AuditService
from app.services.state_service import StateService
from app.core.config import JOURNAL_IMAGE_DIR

router = APIRouter(prefix='/states')

def fmt(s):
    if not s: return None
    images = safe_json(s.get('images_json'), []) or []
    return {**s, 'journal_title': s.get('journal_title') or '未命名的一天',
            'emotions': safe_json(s.get('emotions'), []), 'images': images,
            'image_urls': [f'/journal-images/{name}' for name in images],
            'reward_granted': bool(s.get('reward_granted'))}

@router.get('/today')
def get_today(request: Request): return fmt(StateService(db(request)).get(today()))

@router.post('/today')
def save_today(payload: StateSave, request: Request):
    raise400(StateService(db(request)).save, payload.journal_title, payload.rating, payload.emotions, payload.social_type, payload.social_feeling, payload.energy, payload.review_text, today())
    # 日记审计只记元数据，不把正文写进审计表（隐私最小化）。
    AuditService(db(request)).record(
        actor=actor_of(request), action='state.save', target_type='daily_state',
        params={'date': today(), 'journal_title': payload.journal_title, 'rating': payload.rating,
                'energy': payload.energy, 'has_text': bool((payload.review_text or '').strip())},
        result={'ok': True},
    )
    return {'ok': True, 'state': fmt(StateService(db(request)).get(today()))}

@router.post('/today/images')
async def upload_today_images(request: Request, files: list[UploadFile] = File(...)):
    svc = StateService(db(request)); date = today(); state = svc.get(date)
    if not state: raise HTTPException(status_code=400, detail='请先保存今日日记，再上传图片')
    current = safe_json(state.get('images_json'), []) or []
    if len(current) + len(files) > 6: raise HTTPException(status_code=400, detail='每天最多保存 6 张图片')
    allowed = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif'}
    created = []
    try:
        for upload in files:
            suffix = allowed.get(upload.content_type or '')
            if not suffix: raise HTTPException(status_code=400, detail='仅支持 JPG、PNG、WebP 或 GIF 图片')
            content = await upload.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024: raise HTTPException(status_code=400, detail='单张图片不能超过 8MB')
            name = f'{date}-{uuid4().hex}{suffix}'
            path = JOURNAL_IMAGE_DIR / name
            path.write_bytes(content); created.append(name)
    except Exception:
        for name in created:
            (JOURNAL_IMAGE_DIR / name).unlink(missing_ok=True)
        raise
    images = current + created
    svc.repo.set_images(date, images)
    return {'ok': True, 'state': fmt(svc.get(date))}

@router.delete('/today/images/{filename}')
def delete_today_image(filename: str, request: Request):
    svc = StateService(db(request)); date = today(); state = svc.get(date)
    if not state: raise HTTPException(status_code=404, detail='今日日记不存在')
    safe_name = Path(filename).name
    current = safe_json(state.get('images_json'), []) or []
    if safe_name not in current: raise HTTPException(status_code=404, detail='图片不存在')
    svc.repo.set_images(date, [name for name in current if name != safe_name])
    (JOURNAL_IMAGE_DIR / safe_name).unlink(missing_ok=True)
    return {'ok': True, 'state': fmt(svc.get(date))}

@router.post('/today/images/reorder')
def reorder_today_images(payload: ImageOrder, request: Request):
    svc = StateService(db(request)); date = today(); state = svc.get(date)
    if not state: raise HTTPException(status_code=404, detail='今日日记不存在')
    current = safe_json(state.get('images_json'), []) or []
    requested = [Path(name).name for name in payload.images]
    if len(requested) != len(current) or len(set(requested)) != len(requested) or set(requested) != set(current):
        raise HTTPException(status_code=400, detail='图片顺序数据已过期，请重新操作')
    svc.repo.set_images(date, requested)
    return {'ok': True, 'state': fmt(svc.get(date))}

@router.get('/recent')
def recent(request: Request, limit: int = Query(default=30, ge=1, le=300)):
    return [fmt(s) for s in StateService(db(request)).repo.list_recent(limit)]
