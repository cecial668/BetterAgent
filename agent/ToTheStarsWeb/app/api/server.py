from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import threading
import time

from app.core.config import FRONTEND_DIR, JOURNAL_IMAGE_DIR
from app.db.database import Database
from app.repositories.session_repo import SessionRepo
from app.services.backup_service import BackupService
from app.services.settlement_service import SettlementService
from app.core.date_utils import today_str, prev_date, seconds_until_next_boundary, DAY_BOUNDARY_HOUR
from app.api import (
    routes_agent,
    routes_system,
    routes_quests,
    routes_settlements,
    routes_legends,
    routes_rewards,
    routes_states,
    routes_vacations,
    routes_stats,
    routes_focus,
    routes_schedule,
)


def _run_catch_up(db: Database, last: str | None, current: str) -> list[dict]:
    if not last or last >= current:
        return []
    return SettlementService(db).catch_up(last, current)


def _start_rollover_worker(app: FastAPI) -> None:
    """
    在线日终结算线程。

    原问题：
    如果用户在日终结算时间点仍然在线，旧版本不会自动结算。
    用户稍后关闭软件时，closed_at 又会落在新的一天，导致下次启动时
    系统误以为前一天不需要补结算，从而丢失前一天的日终结算。

    新方案：
    1. 系统日界线改为凌晨 4 点。
    2. 程序在线时，后台线程等待到下一次凌晨 4 点。
    3. 到点后自动对“前一个逻辑日”执行 settle_day。
    4. 结算结果放入 app.state.rollover_results。
    5. 前端通过 /api/rollover-status 轮询并弹窗展示。
    """
    if getattr(app.state, 'rollover_worker_started', False):
        return

    app.state.rollover_worker_started = True
    app.state.rollover_results = []
    app.state.rollover_last_handled_date = None
    app.state.rollover_stop = False

    def worker():
        while not getattr(app.state, 'rollover_stop', False):
            sleep_seconds = seconds_until_next_boundary() + 2
            time.sleep(max(1, sleep_seconds))

            if getattr(app.state, 'rollover_stop', False):
                break

            current = today_str()
            target = prev_date(current)

            if getattr(app.state, 'rollover_last_handled_date', None) == target:
                continue

            try:
                result = SettlementService(app.state.db).settle_day(target)
                app.state.rollover_last_handled_date = target
                app.state.rollover_results.append(result)
            except Exception as exc:
                app.state.rollover_results.append({
                    'date': target,
                    'day_title': '在线日终结算失败',
                    'explain': str(exc),
                })

    threading.Thread(
        target=worker,
        daemon=True,
        name='to-the-stars-rollover',
    ).start()


def create_app() -> FastAPI:
    BackupService().run_startup_backup()

    db = Database()
    SettlementService(db).repair_stranded_quests(today_str())
    session = SessionRepo(db)

    last = session.last_closed_date()
    current = today_str()

    session.open()

    startup_results = []
    try:
        startup_results = _run_catch_up(db, last, current)
    except Exception as exc:
        startup_results = [{
            'date': last,
            'day_title': '补结算失败',
            'explain': str(exc),
        }]

    app = FastAPI(title='向着星 Web MVP', version='web-mvp')

    app.state.db = db
    app.state.session = session
    app.state.last_session_date = last
    app.state.startup_results = startup_results
    app.state.day_boundary_hour = DAY_BOUNDARY_HOUR

    app.include_router(routes_system.router, prefix='/api')
    app.include_router(routes_agent.router, prefix='/api')
    app.include_router(routes_quests.router, prefix='/api')
    app.include_router(routes_settlements.router, prefix='/api')
    app.include_router(routes_legends.router, prefix='/api')
    app.include_router(routes_rewards.router, prefix='/api')
    app.include_router(routes_states.router, prefix='/api')
    app.include_router(routes_vacations.router, prefix='/api')
    app.include_router(routes_stats.router, prefix='/api')
    app.include_router(routes_focus.router, prefix='/api')
    app.include_router(routes_schedule.router, prefix='/api')

    app.mount('/static', StaticFiles(directory=str(FRONTEND_DIR)), name='static')
    app.mount('/journal-images', StaticFiles(directory=str(JOURNAL_IMAGE_DIR)), name='journal-images')

    @app.get('/')
    def index():
        return FileResponse(str(FRONTEND_DIR / 'index.html'))

    @app.on_event('startup')
    def start_online_rollover():
        _start_rollover_worker(app)

    @app.on_event('shutdown')
    def close_session():
        app.state.rollover_stop = True
        try:
            session.close()
        except Exception:
            pass

    return app
