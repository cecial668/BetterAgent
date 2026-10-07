from fastapi import APIRouter, Request
from app.api.routes_common import db, safe_json
from app.services.stats_service import StatsService
from app.repositories.quest_repo import QuestRepo
from app.services.focus_service import FocusService

router = APIRouter(prefix='/stats')

@router.get('/summary')
def summary(request: Request):
    svc=StatsService(db(request)); done,total,rate=svc.completion_rate(); wallet=svc.wallet.get()
    with db(request).connect() as conn:
        q_active=conn.execute('SELECT COUNT(*) c FROM daily_quests').fetchone()['c']
        legends=conn.execute("SELECT COUNT(*) c FROM legend_quests WHERE status<>'archived'").fetchone()['c']
        rewards=conn.execute("SELECT COUNT(*) c FROM rewards WHERE status<>'archived'").fetchone()['c']
    return {'completion_done_days': done, 'completion_total_days': total, 'completion_rate': rate,
            'wallet': wallet, 'active_quests': q_active, 'legend_count': legends, 'reward_count': rewards}

@router.get('/transactions')
def transactions(request: Request): return StatsService(db(request)).transactions()

@router.get('/states')
def states(request: Request):
    rows = StatsService(db(request)).states()
    return [{**row, 'journal_title': row.get('journal_title') or '未命名的一天',
             'emotions': safe_json(row.get('emotions'), []),
             'images': safe_json(row.get('images_json'), []) or []} for row in rows]

@router.get('/settlements')
def settlements(request: Request): return StatsService(db(request)).settlements()

@router.get('/quests-by-category')
def by_category(request: Request):
    with db(request).connect() as conn:
        return [dict(r) for r in conn.execute('SELECT category, COUNT(*) count, SUM(points) points FROM quest_history GROUP BY category ORDER BY count DESC').fetchall()]

@router.get('/legend-progress')
def legend_progress(request: Request):
    with db(request).connect() as conn:
        return [dict(r) for r in conn.execute('''SELECT l.id,l.title,l.status,l.deadline,COUNT(i.id) total,SUM(CASE WHEN i.is_completed THEN 1 ELSE 0 END) done
                                                FROM legend_quests l LEFT JOIN legend_indicators i ON i.legend_id=l.id
                                                GROUP BY l.id ORDER BY l.status,l.deadline''').fetchall()]


@router.get('/focus')
def focus(request: Request, days: int = 14):
    return FocusService(db(request)).summary(days)
