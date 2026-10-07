"""Agent 操作审计存取。

记录"谁（actor）在什么时候对什么对象做了什么"，并携带撤销所需的载荷。
表结构见 app/db/database.py 的 agent_audit；本仓储只做存取，不执行业务规则。
"""
from __future__ import annotations

import json

from app.core.date_utils import now_str


class AuditRepo:
    def __init__(self, db):
        self.db = db

    def record(
        self,
        actor: str,
        action: str,
        target_type: str = '',
        target_id: int | None = None,
        params: dict | None = None,
        result: dict | None = None,
        undo_payload: dict | None = None,
        undoable: bool = False,
    ) -> int:
        with self.db.tx() as conn:
            cur = conn.execute(
                'INSERT INTO agent_audit(created_at,actor,action,target_type,target_id,params_json,result_json,undo_payload_json,undoable) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
                (
                    now_str(),
                    (actor or 'me').strip() or 'me',
                    action,
                    target_type or '',
                    target_id,
                    json.dumps(params or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    json.dumps(undo_payload, ensure_ascii=False) if undo_payload is not None else '',
                    1 if undoable else 0,
                ),
            )
            return cur.lastrowid

    def get(self, audit_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM agent_audit WHERE id=?', (int(audit_id),)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50, actor: str | None = None) -> list[dict]:
        sql = 'SELECT * FROM agent_audit'
        args: list = []
        if actor:
            sql += ' WHERE actor=?'
            args.append(actor)
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(max(1, min(int(limit), 500)))
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def mark_undone(self, audit_id: int, note: str = '') -> None:
        with self.db.tx() as conn:
            conn.execute(
                'UPDATE agent_audit SET undone_at=?, undo_note=? WHERE id=? AND undone_at=?',
                (now_str(), note or '', int(audit_id), ''),
            )
