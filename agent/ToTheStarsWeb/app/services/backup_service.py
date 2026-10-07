import shutil
from app.core.config import DB_PATH, BACKUP_DIR, BACKUP_KEEP
from datetime import datetime
class BackupService:
    def run_startup_backup(self):
        if DB_PATH.exists():
            target=BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(DB_PATH, target)
        backups=sorted(BACKUP_DIR.glob('backup_*.db'), key=lambda p:p.stat().st_mtime, reverse=True)
        for p in backups[BACKUP_KEEP:]:
            try: p.unlink()
            except OSError: pass
