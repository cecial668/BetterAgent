"""BetterAgent × 向着星 联动 —— 自动化验收（设计文档 §11 / §12.3）。

用法（在 BetterAgent 仓库根目录、用项目 venv 运行）：

    python scripts/acceptance_tothestars.py

需要：
  - 正在运行的 BetterAgent 无关；脚本自带 Go 单测子进程（需 PATH 中有 go）；
  - 把向着星仓库路径通过环境变量指过来（默认按作者机器的路径，可覆盖）：
        set TOTHESTARS_ROOT=E:\\path\\to\\ToTheStarsWeb
  - 依赖：httpx / fastapi / uvicorn / ruamel.yaml（BetterAgent 的 admin 依赖里已有）。

覆盖 8 组验收：权限门控 / 快照一致性 / 写入确认 / 审计撤销 / 日记边界 /
静默与频率（Go 单测）/ 离线降级 / HUD Admin 代理。全部使用临时实例与临时库。
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BA_ROOT = Path(__file__).resolve().parents[1]
TS_ROOT = Path(os.getenv(
    'TOTHESTARS_ROOT',
    r'E:\ToTheStars\ToTheStarsV26-6-1\ToTheStarsWeb_react_frontend_full\ToTheStarsWeb\ToTheStarsWeb',
))
if not (TS_ROOT / 'app' / 'api' / 'server.py').exists():
    sys.exit(f'找不到向着星仓库：{TS_ROOT}（用环境变量 TOTHESTARS_ROOT 指定）')

sys.path.insert(0, str(TS_ROOT))
sys.path.insert(0, str(BA_ROOT))

TMP = Path(tempfile.mkdtemp(prefix='acceptance_'))
TS_PORT = 18773
TS_URL = f'http://127.0.0.1:{TS_PORT}'

RESULTS = []


def check(step, label, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    RESULTS.append((step, label, condition, detail))
    print(f'[{status}] ({step}) {label}' + (f' -- {detail}' if detail and not condition else ''))
    if not condition:
        raise SystemExit(1)


# ---------------------------------------------------------------- ToTheStars
import app.core.config as ts_config  # noqa: E402

ts_config.DATA_DIR = TMP / 'data'
ts_config.BACKUP_DIR = TMP / 'backups'
ts_config.LOG_DIR = TMP / 'logs'
ts_config.EXPORT_DIR = TMP / 'exports'
ts_config.JOURNAL_IMAGE_DIR = ts_config.DATA_DIR / 'journal_images'
ts_config.DB_PATH = ts_config.DATA_DIR / 'growth_system.db'
for _d in (ts_config.DATA_DIR, ts_config.BACKUP_DIR, ts_config.LOG_DIR, ts_config.EXPORT_DIR, ts_config.JOURNAL_IMAGE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import uvicorn  # noqa: E402
from app.api.server import create_app  # noqa: E402

ts_server = uvicorn.Server(uvicorn.Config(create_app(), host='127.0.0.1', port=TS_PORT, log_level='warning'))
threading.Thread(target=ts_server.run, daemon=True).start()
for _ in range(100):
    if ts_server.started:
        break
    time.sleep(0.05)
check('setup', '向着星临时实例已启动', ts_server.started)

import httpx  # noqa: E402

http = httpx.Client(base_url=TS_URL, timeout=5.0, trust_env=False)

# ---------------------------------------------------------------- admin 后端
os.environ['TOTHESTARS_URL'] = TS_URL
os.environ['ADMIN_DB_PATH'] = str(TMP / 'admin.db')
os.environ['PERSONA_DIR'] = str(TMP / 'persona')
os.environ['ADMIN_SECRET_KEY'] = ''
(TMP / 'persona').mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BA_ROOT / 'admin' / 'backend'))
import main as admin_main  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

admin = TestClient(admin_main.app)

# ---------------------------------------------------------------- BetterAgent
import shared.config_loader as ba_config  # noqa: E402
import services.cognitive.prompt_builder as pb  # noqa: E402
from services.cognitive.cognitive_engine import CognitiveEngine  # noqa: E402
from services.cognitive.tools import tothestars_tool as tt  # noqa: E402
from shared import life_data_permissions as perms  # noqa: E402
from shared.schema.payloads import (
    InboundMessagePayload,
    LifeProposalPayload,
    ReasoningRequestPayload,
    ToolActivityPayload,
)  # noqa: E402


def set_permissions(permissions=None, enabled=True):
    section = {'enabled': enabled, 'endpoint': TS_URL, 'timeout_seconds': 2.0}
    if permissions is not None:
        section['permissions'] = permissions
    ba_config._cached_config = {'integration': {'tothestars': section}}


def payload_for(text):
    return ReasoningRequestPayload(
        chat_id=1001, user_id=1, trigger_type='user_message',
        inbound_message=InboundMessagePayload(chat_id=1001, user_id=1, message_id=1, raw_text=text),
    )


ALL_HIDDEN = {c: 'hidden' for c in perms.DEFAULT_PERMISSIONS}

# ---- A1 权限全关 ----
set_permissions(ALL_HIDDEN)
visible = [name for name in perms.TOOL_CATEGORY if perms.is_tool_visible(name)]
visible += [n for n in perms.WRITE_TOOL_CATEGORY if perms.is_tool_visible(n)]
check('A1', '权限全关时没有任何生活数据工具可见', visible == [], visible)

calls = []
original_fetch = pb.fetch_life_snapshot_block
pb.fetch_life_snapshot_block = lambda: calls.append(1) or 'SHOULD_NOT_APPEAR'
try:
    prompt = pb.PromptBuilder.build_system_prompt(payload_for('今天有什么没做？'))
finally:
    pb.fetch_life_snapshot_block = original_fetch
check('A1', '权限全关时提示词不注入生活快照', 'SHOULD_NOT_APPEAR' not in prompt and not calls)

# ---- A2 开启读权限后数据一致 ----
set_permissions()
check('A2', '委托读工具可见', perms.is_tool_visible('tothestars_get_commissions'))
check('A2', '日记正文保持不可读（默认最小权限）', not perms.can_read('journal_text'))

client = tt.TothestarsClient()
http.post('/api/quests', json={'title': '验收委托 A2', 'difficulty': 'B', 'is_required': True},
          headers={'X-Actor': 'companion'})
snap = asyncio.run(tt.ToTheStarsLifeSnapshotTool(client).execute())
page_quests = http.get('/api/quests').json()
check('A2', '快照工具成功', snap['status'] == 'success', snap)
tool_titles = sorted(q['title'] for q in snap['data']['commissions'])
page_titles = sorted(q['title'] for q in page_quests)
check('A2', '快照数据与页面一致', tool_titles == page_titles, (tool_titles, page_titles))

# ---- A3 写入必须确认 ----
engine = CognitiveEngine()
proposal = asyncio.run(tt.CreateCommissionProposalTool(client).execute(title='验收委托 A3', difficulty='A'))
engine._capture_life_proposal(payload_for('加到委托里'), proposal)
check('A3', '提议阶段零写入', all(q['title'] != '验收委托 A3' for q in http.get('/api/quests').json()))


def settle(text, eng=engine):
    messages = []
    events = []
    async def _run():
        async for event in eng._settle_pending_life_action(payload_for(text), messages):
            events.append(event)
    asyncio.run(_run())
    return events, messages


settle('我等会儿再想想')
check('A3', '未确认（答非所问）零写入', all(q['title'] != '验收委托 A3' for q in http.get('/api/quests').json()))

proposal = asyncio.run(tt.CreateCommissionProposalTool(client).execute(title='验收委托 A3', difficulty='A'))
engine._capture_life_proposal(payload_for('加到委托里'), proposal)
events, messages = settle('好的')
created = next((q for q in http.get('/api/quests').json() if q['title'] == '验收委托 A3'), None)
check('A3', '确认后落库', created is not None)
tool_events = [e for e in events if isinstance(e, ToolActivityPayload)]
proposal_phases = [e.phase for e in events if isinstance(e, LifeProposalPayload)]
check('A3', '执行时发出工具活动字幕事件',
      [e.phase for e in tool_events] == ['start', 'done'] and bool(tool_events[0].label), tool_events)
check('A3', '确认框事件相位 executing→executed', proposal_phases == ['executing', 'executed'], proposal_phases)

# ---- A4 审计与撤销 ----
entries = http.get('/api/agent/audit?limit=50').json()
entry = next((e for e in entries if e['action'] == 'quest.create' and e['actor'] == 'companion'
              and e['target_id'] == created['id']), None)
check('A4', '写入在 agent_audit 留痕（actor=companion）', entry is not None)
undo = http.post(f"/api/agent/audit/{entry['id']}/undo")
check('A4', '一键撤销成功', undo.status_code == 200, undo.text)
check('A4', '撤销后委托消失', all(q['title'] != '验收委托 A3' for q in http.get('/api/quests').json()))
check('A4', '撤销本身也留痕', any(e['action'] == 'audit.undo' for e in http.get('/api/agent/audit').json()))

# ---- A5 日记 on_request 不进主动简报 ----
http.post('/api/states/today', json={'journal_title': '验收日记', 'rating': 4, 'emotions': ['平静'],
                                     'social_type': '独处', 'social_feeling': 0, 'energy': 1,
                                     'review_text': '验收正文不应进提示词。'},
          headers={'X-Actor': 'companion'})
block = original_fetch()
check('A5', 'on_request 日记不进主动简报', '今日心情' not in block, block)
check('A5', '日记标题/正文不进提示词', '验收日记' not in block and '验收正文' not in block, block)
journal_tool = asyncio.run(tt.ToTheStarsJournalSummaryTool(client).execute(include_text=True))
check('A5', '明确问起时可读摘要，但正文与照片仍被裁剪',
      journal_tool['status'] == 'success'
      and journal_tool['data'].get('review_text') is None
      and 'images' not in (journal_tool['data'] or {}), journal_tool)

# ---- A6 静默时段 / 频率上限（Go 单测） ----
go_test = subprocess.run(
    ['go', 'test', './internal/engine/', '-run', 'QuietHours|Cap', '-count=1'],
    cwd=str(BA_ROOT / 'core'), capture_output=True, text=True,
)
check('A6', '静默时段与频率上限单测通过', go_test.returncode == 0,
      (go_test.stdout + go_test.stderr)[-400:])

# ---- A7 服务不可达时友好失败 ----
dead = tt.TothestarsClient(endpoint='http://127.0.0.1:9', timeout=0.5)
failed = asyncio.run(tt.ToTheStarsCommissionsTool(dead).execute())
check('A7', '不可达时返回友好失败且不抛异常',
      failed['status'] == 'failed' and '不要编造' in failed['message'], failed)

# ---- A8 HUD 的 Admin 代理 ----
proxied = admin.get('/api/admin/tothestars/snapshot')
check('A8', 'Admin 代理可读生活快照', proxied.status_code == 200 and 'date' in proxied.json(), proxied.text)
admin_main.TOTHESTARS_URL = 'http://127.0.0.1:9'
down = admin.get('/api/admin/tothestars/snapshot')
check('A8', '向着星不可达时代理返回干净 503', down.status_code == 503, down.text)

ts_server.should_exit = True
time.sleep(0.3)

print('\n================ 验收汇总 ================')
for step, label, ok, _ in RESULTS:
    print(f'  [{"ok" if ok else "XX"}] {step} {label}')
print(f'共 {len(RESULTS)} 项，全部通过。')
print('ACCEPTANCE OK')
