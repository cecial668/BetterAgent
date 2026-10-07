import json
from app.core.date_utils import now_str
class StateRepo:
    def __init__(self, db): self.db=db
    def get(self, date):
        with self.db.connect() as conn:
            r=conn.execute('SELECT * FROM daily_states WHERE date=?',(date,)).fetchone()
            return dict(r) if r else None
    def save(self, date, journal_title, rating, emotions, social_type, social_feeling, energy, review_text):
        old=self.get(date); now=now_str()
        with self.db.tx() as conn:
            sql=('INSERT INTO daily_states(date,journal_title,rating,emotions,social_type,social_feeling,energy,review_text,images_json,reward_granted,created_at,updated_at) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET journal_title=excluded.journal_title,rating=excluded.rating,emotions=excluded.emotions,social_type=excluded.social_type,social_feeling=excluded.social_feeling,energy=excluded.energy,review_text=excluded.review_text,updated_at=excluded.updated_at')
            conn.execute(sql,(date,journal_title,rating,json.dumps(emotions,ensure_ascii=False),social_type,social_feeling,energy,review_text,old.get('images_json','[]') if old else '[]',old['reward_granted'] if old else 0,now,now))
    def set_images(self, date, images):
        with self.db.tx() as conn:
            conn.execute('UPDATE daily_states SET images_json=?, updated_at=? WHERE date=?', (json.dumps(images, ensure_ascii=False), now_str(), date))
    def mark_reward(self, date, conn): conn.execute('UPDATE daily_states SET reward_granted=1, updated_at=? WHERE date=?',(now_str(),date))
    def list_recent(self, limit=100):
        with self.db.connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM daily_states ORDER BY date DESC LIMIT ?',(limit,)).fetchall()]
