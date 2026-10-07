from app.core.date_utils import now_str, business_date_from_datetime_string


class SessionRepo:
    def __init__(self, db):
        self.db = db
        self.current_id = None

    def last_closed_date(self):
        """
        返回上一次会话涉及到的最早逻辑日期。

        这里不能只看 closed_at。
        因为如果用户 5月19日晚上打开软件，5月20日凌晨5点关闭软件，
        closed_at 的逻辑日期已经是 5月20日。
        如果只看 closed_at，系统会误以为 5月19日已经不需要补结算，
        从而造成日终结算丢失。

        所以这里同时看 opened_at 和 closed_at，并返回较早的逻辑日期。
        如果这一天已经在线自动结算过，SettlementService.catch_up 会因为
        daily_settlements 中已有记录而不会重复结算。
        """
        with self.db.connect() as conn:
            r = conn.execute(
                'SELECT opened_at, closed_at FROM app_sessions ORDER BY id DESC LIMIT 1'
            ).fetchone()

            if not r:
                return None

            dates = [
                business_date_from_datetime_string(r['opened_at']),
                business_date_from_datetime_string(r['closed_at']),
            ]
            dates = [d for d in dates if d]

            return min(dates) if dates else None

    def open(self):
        with self.db.tx() as conn:
            cur = conn.execute(
                'INSERT INTO app_sessions(opened_at, closed_normally) VALUES(?, 0)',
                (now_str(),),
            )
            self.current_id = cur.lastrowid

    def close(self):
        if self.current_id:
            with self.db.tx() as conn:
                conn.execute(
                    'UPDATE app_sessions SET closed_at=?, closed_normally=1 WHERE id=?',
                    (now_str(), self.current_id),
                )