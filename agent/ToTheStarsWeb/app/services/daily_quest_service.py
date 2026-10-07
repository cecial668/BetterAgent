from app.core.constants import DIFFICULTY_META
from app.repositories.quest_repo import QuestRepo
from app.repositories.log_repo import LogRepo
from app.core.date_utils import today_str


class DailyQuestService:
    def __init__(self, db):
        self.db = db
        self.repo = QuestRepo(db)
        self.log = LogRepo(db)

    def list(self, date=None):
        return self.repo.list_by_date(date or today_str())

    def create(self, title, description, difficulty, category, is_required, date=None, is_recurring=False):
        if not title.strip():
            raise ValueError('委托名称不能为空')
        meta = DIFFICULTY_META[difficulty]
        qid = self.repo.create(
            title.strip(),
            description,
            difficulty,
            meta['points'],
            category,
            int(is_required),
            date or today_str(),
            int(is_recurring),
        )
        self.log.log('create', 'daily_quest', qid, {'title': title, 'is_recurring': bool(is_recurring)})
        return qid

    def update(self, qid, title, description, difficulty, category, is_required, is_recurring=False):
        meta = DIFFICULTY_META[difficulty]
        self.repo.update(qid, title, description, difficulty, meta['points'], category, is_required, int(is_recurring))
        self.log.log('update', 'daily_quest', qid, {'is_recurring': bool(is_recurring)})

    def set_completed(self, qid, completed):
        self.repo.set_completed(qid, completed)
        self.log.log('complete' if completed else 'uncomplete', 'daily_quest', qid, {})

    def delete(self, qid):
        self.repo.delete(qid)
        self.log.log('delete', 'daily_quest', qid, {})

    @staticmethod
    def _batch_ids(ids):
        normalized = list(dict.fromkeys(int(qid) for qid in ids))
        if not normalized or any(qid <= 0 for qid in normalized):
            raise ValueError('请选择至少一项有效委托')
        return normalized

    def batch_complete(self, ids):
        normalized = self._batch_ids(ids)
        with self.db.tx() as conn:
            completed = self.repo.batch_set_completed(normalized, conn)
            self.log.log('batch_complete', 'daily_quest', None, {'ids': completed, 'count': len(completed)}, conn)
        return completed

    def batch_delete(self, ids):
        normalized = self._batch_ids(ids)
        with self.db.tx() as conn:
            deleted = self.repo.batch_delete(normalized, conn)
            self.log.log('batch_delete', 'daily_quest', None, {'ids': deleted, 'count': len(deleted), 'wallet_unchanged': True}, conn)
        return deleted

    def condition(self, date=None):
        qs = self.list(date)
        total = sum(float(q['points']) for q in qs if q['is_completed'])
        required_all = all(q['is_completed'] for q in qs if q['is_required'])
        return {'total': total, 'required_all': required_all, 'success': total >= 4 and required_all}
