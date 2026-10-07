"""面向数字人的 Agent 接口测试：快照 / 审计 / 撤销。

隔离策略：在导入任何 app 模块之前，把 app.core.config 的所有路径指到临时
目录，确保测试绝不会读写真实的 data/growth_system.db。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.core.config as config  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix='tothestars_agent_test_'))
config.DATA_DIR = _TMP / 'data'
config.BACKUP_DIR = _TMP / 'backups'
config.LOG_DIR = _TMP / 'logs'
config.EXPORT_DIR = _TMP / 'exports'
config.JOURNAL_IMAGE_DIR = config.DATA_DIR / 'journal_images'
config.DB_PATH = config.DATA_DIR / 'growth_system.db'
for _dir in (config.DATA_DIR, config.BACKUP_DIR, config.LOG_DIR, config.EXPORT_DIR, config.JOURNAL_IMAGE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.server import create_app  # noqa: E402

_API = '/api'

# 不进入 context manager：跳过 startup 事件（不会启动轮询回滚线程），
# create_app() 本身已完成数据库初始化。
_CLIENT = TestClient(create_app())


@pytest.fixture()
def client():
    return _CLIENT


def _create_quest(client, title='取快递', difficulty='B', actor='companion', **extra):
    body = {'title': title, 'difficulty': difficulty, **extra}
    headers = {'X-Actor': actor} if actor else {}
    return client.post(f'{_API}/quests', json=body, headers=headers)


def test_snapshot_shape(client):
    res = client.get(f'{_API}/agent/snapshot')
    assert res.status_code == 200
    data = res.json()
    for key in ('date', 'condition', 'wallet', 'commissions', 'schedule', 'legends', 'journal'):
        assert key in data
    assert isinstance(data['commissions'], list)


def test_chat_config_disabled_without_token(client, monkeypatch):
    import app.api.routes_agent as routes_agent
    monkeypatch.setattr(routes_agent, 'AGENT_WS_TOKEN', '', raising=False)
    data = client.get(f'{_API}/agent/chat-config').json()
    assert data['enabled'] is False
    assert data['ws_url'].startswith('ws://')
    assert data['token'] == ''


def test_chat_config_enabled_with_token(client, monkeypatch):
    import app.api.routes_agent as routes_agent
    monkeypatch.setattr(routes_agent, 'AGENT_WS_TOKEN', 'secret-token')
    monkeypatch.setattr(routes_agent, 'AGENT_WS_URL', 'ws://127.0.0.1:8080/ws')
    monkeypatch.setattr(routes_agent, 'AGENT_CHAT_ID', 1001)
    data = client.get(f'{_API}/agent/chat-config').json()
    assert data['enabled'] is True
    assert data['token'] == 'secret-token'
    assert data['chat_id'] == 1001


def test_quest_create_is_audited_as_companion_and_undoable(client):
    res = _create_quest(client)
    assert res.status_code == 200
    qid = res.json()['id']

    audit = client.get(f'{_API}/agent/audit').json()
    entry = next(e for e in audit if e['action'] == 'quest.create' and e['target_id'] == qid)
    assert entry['actor'] == 'companion'
    assert entry['undoable'] is True
    assert entry['undone'] is False

    undo = client.post(f'{_API}/agent/audit/{entry["id"]}/undo', headers={'X-Actor': 'me'})
    assert undo.status_code == 200

    quests = client.get(f'{_API}/quests').json()
    assert all(q['id'] != qid for q in quests)
    audit_after = client.get(f'{_API}/agent/audit').json()
    assert any(e['action'] == 'audit.undo' for e in audit_after)


def test_complete_then_undo_restores_incomplete(client):
    qid = _create_quest(client, title='写周报').json()['id']
    done = client.post(f'{_API}/quests/{qid}/complete', json={'completed': True}, headers={'X-Actor': 'companion'})
    assert done.status_code == 200

    audit = client.get(f'{_API}/agent/audit').json()
    entry = next(e for e in audit if e['action'] == 'quest.complete' and e['target_id'] == qid)
    assert client.post(f'{_API}/agent/audit/{entry["id"]}/undo').status_code == 200

    quests = client.get(f'{_API}/quests').json()
    quest = next(q for q in quests if q['id'] == qid)
    assert quest['is_completed'] is False


def test_undo_twice_is_rejected(client):
    qid = _create_quest(client, title='撤销两次').json()['id']
    audit = client.get(f'{_API}/agent/audit').json()
    entry = next(e for e in audit if e['action'] == 'quest.create' and e['target_id'] == qid)
    assert client.post(f'{_API}/agent/audit/{entry["id"]}/undo').status_code == 200
    assert client.post(f'{_API}/agent/audit/{entry["id"]}/undo').status_code == 400


def test_schedule_create_is_audited_and_undoable(client):
    qid = _create_quest(client, title='练琴').json()['id']
    plan = client.post(
        f'{_API}/schedule/plans',
        json={'quest_id': qid, 'start': '20:00', 'end': '21:00'},
        headers={'X-Actor': 'companion'},
    )
    assert plan.status_code == 200
    plan_id = plan.json()['plan']['id']

    audit = client.get(f'{_API}/agent/audit').json()
    entry = next(e for e in audit if e['action'] == 'schedule.create' and e['target_id'] == plan_id)
    assert client.post(f'{_API}/agent/audit/{entry["id"]}/undo').status_code == 200

    day = client.get(f'{_API}/schedule/day').json()
    assert all(p['id'] != plan_id for p in day['plans'])


def test_snapshot_includes_created_quest_and_plan(client):
    qid = _create_quest(client, title='快照校验').json()['id']
    client.post(
        f'{_API}/schedule/plans',
        json={'quest_id': qid, 'start': '09:00', 'end': '10:00'},
        headers={'X-Actor': 'companion'},
    )
    snap = client.get(f'{_API}/agent/snapshot').json()
    assert any(q['id'] == qid for q in snap['commissions'])
    assert any(p['quest_id'] == qid for p in snap['schedule']['plans'])
