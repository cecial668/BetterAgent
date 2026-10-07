import json
from app.core.date_utils import now_str
class LogRepo:
    def __init__(self, db): self.db=db
    def log(self, action_type, target_type, target_id=None, detail=None, conn=None):
        own=conn is None; conn=conn or self.db.connect()
        try:
            conn.execute('INSERT INTO operation_logs(timestamp,action_type,target_type,target_id,detail) VALUES(?,?,?,?,?)',
                         (now_str(), action_type, target_type, target_id, json.dumps(detail or {}, ensure_ascii=False)))
            if own: conn.commit()
        finally:
            if own: conn.close()
