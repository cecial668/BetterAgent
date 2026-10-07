from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]
HOST = '127.0.0.1'
PORT = 8765
DATA_DIR = BASE_DIR / 'data'
BACKUP_DIR = BASE_DIR / 'backups'
LOG_DIR = BASE_DIR / 'logs'
EXPORT_DIR = BASE_DIR / 'exports'
JOURNAL_IMAGE_DIR = DATA_DIR / 'journal_images'
FRONTEND_DIR = BASE_DIR / 'frontend'
DB_PATH = DATA_DIR / 'growth_system.db'
BACKUP_KEEP = 10
for _d in (DATA_DIR, BACKUP_DIR, LOG_DIR, EXPORT_DIR, JOURNAL_IMAGE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# BetterAgent 数字人对话气泡（右下角）。缺省关闭：没配 token 前端就不渲染气泡，
# 旧部署零变化。token 即 BetterAgent WebGateway 的 WEBGATEWAY_TOKEN，两端都在
# 本机（127.0.0.1）通信，见 docs/TOTHESTARS-INTEGRATION-PLAN.md。
# ---------------------------------------------------------------------------
AGENT_WS_URL = os.getenv('AGENT_WS_URL', 'ws://127.0.0.1:8080/ws')


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, '') or default)
    except (TypeError, ValueError):
        return default


AGENT_CHAT_ID = _env_int('AGENT_CHAT_ID', 1001)
AGENT_WS_TOKEN = os.getenv('AGENT_WS_TOKEN', '')
