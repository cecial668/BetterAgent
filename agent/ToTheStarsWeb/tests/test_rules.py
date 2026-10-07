"""轻量手动/开发测试入口。正式运行项目不依赖 pytest。"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.database import Database
from app.services.daily_quest_service import DailyQuestService
from app.services.settlement_service import SettlementService
from app.services.wallet_service import WalletService
from app.services.state_service import StateService
from app.services.legend_service import LegendService
from app.core.date_utils import now_str


def smoke_test():
    db = Database()
    quests = DailyQuestService(db)
    settle = SettlementService(db)
    wallet = WalletService(db)
    assert wallet.get()['practice_points'] >= 0
    assert isinstance(quests.list(), list)
    assert isinstance(settle.catch_up(None), list)


def regression_test_multiday_carry_over():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'carry-over.db')
        with db.tx() as conn:
            conn.execute('''INSERT INTO daily_quests(title,description,difficulty,points,category,is_required,is_recurring,is_completed,assigned_date,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', ('跨日委托','', 'A', 1, '测试', 0, 0, 0, '2026-08-28', now_str(), now_str()))
        results = SettlementService(db).catch_up('2026-08-28', '2026-08-31')
        with db.connect() as conn:
            quest = conn.execute('SELECT assigned_date FROM daily_quests WHERE title=?', ('跨日委托',)).fetchone()
        assert quest and quest['assigned_date'] == '2026-08-31'
        assert [item['date'] for item in results] == ['2026-08-28', '2026-08-29', '2026-08-30']

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'settled-gap.db')
        with db.tx() as conn:
            conn.execute('''INSERT INTO daily_quests(title,description,difficulty,points,category,is_required,is_recurring,is_completed,assigned_date,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', ('跨过空结算日','', 'A', 1, '测试', 0, 0, 0, '2026-08-28', now_str(), now_str()))
        SettlementService(db).create_absent_settlement('2026-08-29')
        SettlementService(db).catch_up('2026-08-28', '2026-08-31')
        with db.connect() as conn:
            quest = conn.execute('SELECT assigned_date FROM daily_quests WHERE title=?', ('跨过空结算日',)).fetchone()
        assert quest and quest['assigned_date'] == '2026-08-31'


def regression_test_journal_fields():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'journal.db')
        service = StateService(db)
        service.save('微小但明亮的一天', 4, ['平静'], '独处', 0, 1, '今天把重要的事情推进了一小步。', '2026-08-30')
        entry = service.get('2026-08-30')
        assert entry['journal_title'] == '微小但明亮的一天'
        assert entry['images_json'] == '[]'


def regression_test_journal_image_order():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'journal-images.db')
        service = StateService(db)
        service.save('影像顺序测试', 4, ['平静'], '独处', 0, 1, '正文草稿', '2026-09-01')
        service.repo.set_images('2026-09-01', ['cover.jpg', 'second.jpg', 'third.jpg'])
        state = service.get('2026-09-01')
        current = __import__('json').loads(state['images_json'])
        assert current == ['cover.jpg', 'second.jpg', 'third.jpg']
        service.repo.set_images('2026-09-01', ['second.jpg', 'cover.jpg', 'third.jpg'])
        reordered = __import__('json').loads(service.get('2026-09-01')['images_json'])
        assert reordered[0] == 'second.jpg' and set(reordered) == {'cover.jpg', 'second.jpg', 'third.jpg'}


def regression_test_quest_batch_actions():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'quest-batch.db')
        service = DailyQuestService(db)
        first = service.create('批量一', '', 'A', '测试', False, '2026-09-01')
        second = service.create('批量二', '', 'B', '测试', True, '2026-09-01')
        third = service.create('已入池也可删', '', 'C', '测试', False, '2026-09-01')
        service.batch_complete([first, second, first])
        with db.tx() as conn:
            conn.execute('UPDATE point_wallet SET practice_points=12.5 WHERE id=1')
            conn.execute('UPDATE daily_quests SET banked_points=3 WHERE id=?', (third,))
        before = WalletService(db).get()['practice_points']
        service.batch_delete([first, third])
        after = WalletService(db).get()['practice_points']
        rows = service.list('2026-09-01')
        assert [row['id'] for row in rows] == [second]
        assert rows[0]['is_completed'] == 1
        assert before == after == 12.5
        with db.connect() as conn:
            reasons = {row['original_quest_id']: row['archive_reason'] for row in conn.execute('SELECT original_quest_id,archive_reason FROM quest_history').fetchall()}
        assert reasons[first] == 'batch_deleted'
        assert reasons[third] == 'batch_deleted'

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'quest-batch-rollback.db')
        service = DailyQuestService(db)
        existing = service.create('不能被部分处理', '', 'A', '测试', False, '2026-09-01')
        try:
            service.batch_complete([existing, 999999])
            raise AssertionError('缺失委托时批量完成应失败')
        except ValueError:
            pass
        assert service.list('2026-09-01')[0]['is_completed'] == 0
        try:
            service.batch_delete([existing, 999999])
            raise AssertionError('缺失委托时批量删除应失败')
        except ValueError:
            pass
        assert service.list('2026-09-01')[0]['id'] == existing


def regression_test_legend_manual_confirmation():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'legend-confirm.db')
        service = LegendService(db)
        lid = service.create('完成一场长期战役', '确认完成必须独立执行', 'C', '2026-12-31', ['第一阶段', '第二阶段'])
        indicators = service.indicators(lid)

        service.complete_indicator(indicators[0]['id'], True)
        try:
            service.confirm_complete(lid)
            raise AssertionError('指标未全部完成时不应允许确认传说任务')
        except ValueError:
            pass

        service.complete_indicator(indicators[1]['id'], True)
        with db.connect() as conn:
            legend = conn.execute('SELECT status,points_awarded FROM legend_quests WHERE id=?', (lid,)).fetchone()
            wallet_before = conn.execute('SELECT growth_points FROM point_wallet WHERE id=1').fetchone()['growth_points']
        assert legend['status'] == 'active' and legend['points_awarded'] == 0

        service.complete_indicator(indicators[0]['id'], False)
        assert not service.indicators(lid)[0]['is_completed']
        service.complete_indicator(indicators[0]['id'], True)
        assert service.confirm_complete(lid) is True
        assert service.confirm_complete(lid) is False

        with db.connect() as conn:
            legend = conn.execute('SELECT status,points_awarded FROM legend_quests WHERE id=?', (lid,)).fetchone()
            wallet_after = conn.execute('SELECT growth_points FROM point_wallet WHERE id=1').fetchone()['growth_points']
            rewards = conn.execute("SELECT COUNT(*) c FROM point_transactions WHERE reason='legend_complete' AND related_id=?", (lid,)).fetchone()['c']
        assert legend['status'] == 'completed' and legend['points_awarded'] == 1
        assert wallet_after - wallet_before == 3.0
        assert rewards == 1

        try:
            service.complete_indicator(indicators[0]['id'], False)
            raise AssertionError('最终完成后不应再允许回退指标')
        except ValueError:
            pass

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'legend-rollback.db')
        service = LegendService(db)
        lid = service.create('事务回滚战役', '', 'B', '2026-12-31', ['唯一指标'])
        indicator = service.indicators(lid)[0]
        service.complete_indicator(indicator['id'], True)
        original_add_growth = service.wallet.add_growth

        def fail_reward(*args, **kwargs):
            raise RuntimeError('模拟奖励写入失败')

        service.wallet.add_growth = fail_reward
        try:
            service.confirm_complete(lid)
            raise AssertionError('奖励写入失败时确认操作应失败')
        except RuntimeError:
            pass
        finally:
            service.wallet.add_growth = original_add_growth

        with db.connect() as conn:
            legend = conn.execute('SELECT status,points_awarded,completed_at FROM legend_quests WHERE id=?', (lid,)).fetchone()
            rewards = conn.execute("SELECT COUNT(*) c FROM point_transactions WHERE reason='legend_complete' AND related_id=?", (lid,)).fetchone()['c']
        assert legend['status'] == 'active' and legend['points_awarded'] == 0 and legend['completed_at'] is None
        assert rewards == 0


def regression_test_schedule_time_offsets():
    from app.services.schedule_service import (
        assign_lanes,
        offset_to_label,
        parse_time_offset,
    )

    # 逻辑日以凌晨 4 点切换：04:00 是起点，次日 04:00 是终点
    assert parse_time_offset('04:00') == 0
    assert parse_time_offset('09:00') == 300
    assert parse_time_offset('23:30') == 1170
    assert parse_time_offset('00:30') == 1230
    assert parse_time_offset('04:00', as_end=True) == 1440
    assert parse_time_offset('03:59', as_end=True) == 1439
    assert offset_to_label(0) == '04:00'
    assert offset_to_label(1440) == '04:00'
    assert offset_to_label(1170) == '23:30'

    for bad in ('', '25:00', '9', 'aa:bb'):
        try:
            parse_time_offset(bad)
            raise AssertionError(f'{bad} 应该被拒绝')
        except ValueError:
            pass

    # 重叠的计划自动错开到不同行，互不重叠的可以复用同一行
    plans = [
        {'id': 1, 'start_minute': 300, 'end_minute': 450},
        {'id': 2, 'start_minute': 420, 'end_minute': 600},
        {'id': 3, 'start_minute': 600, 'end_minute': 700},
    ]
    lanes = assign_lanes(plans)
    by_id = {p['id']: p['lane'] for p in plans}
    assert lanes == 2
    assert by_id[1] == 0 and by_id[2] == 1 and by_id[3] == 0


def regression_test_schedule_binding_and_views():
    from app.api.schemas import SchedulePlanCreate, SchedulePlanUpdate
    from app.services.schedule_service import ScheduleService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'schedule.db')
        quests = DailyQuestService(db)
        schedule = ScheduleService(db)
        date = '2026-09-07'  # 周一

        math_id = quests.create('数学刷题', '第三章', 'B', '知识', False, date)
        english_id = quests.create('英语精读', '外刊精读', 'A', '知识', False, date)

        first = schedule.create(SchedulePlanCreate(plan_date=date, start='09:00', end='11:30', quest_id=math_id))
        assert first['kind'] == 'quest' and first['color_key'] == 'quest'
        assert first['title'] == '数学刷题' and first['content'] == '第三章'
        assert (first['start_minute'], first['end_minute']) == (300, 450)

        # 重叠的委托计划必须错开到不同行
        second = schedule.create(SchedulePlanCreate(plan_date=date, start='10:00', end='12:00', quest_id=english_id))
        day = schedule.day(date)
        lanes = {p['id']: p['lane'] for p in day['plans']}
        assert lanes[first['id']] == 0 and lanes[second['id']] == 1
        assert day['lane_count'] == 2
        assert [q['title'] for q in day['unscheduled_quests']] == []
        assert all(q['scheduled'] for q in day['quests'])

        # 跨凌晨 4 点的自定义计划
        night = schedule.create(SchedulePlanCreate(plan_date=date, title='夜间冥想', content='放空', start='23:30', end='00:30'))
        assert night['kind'] == 'free' and night['color_key'] == 'free'
        assert night['time_label'] == '23:30 - 00:30'
        assert night['end_minute'] == 1230

        # 委托计划改标题/内容 → 每日委托同步被改写
        schedule.update(first['id'], SchedulePlanUpdate(title='数学刷题（进阶）', content='第四章', start='08:00', end='11:00'))
        bound_quest = [q for q in quests.list(date) if q['id'] == math_id][0]
        assert bound_quest['title'] == '数学刷题（进阶）'
        assert bound_quest['description'] == '第四章'

        # 每日委托改标题 → 计划卡片同步显示最新文案（与 PUT /api/quests/{id} 的流程一致）
        quests.update(math_id, '数学刷题（委托改名）', '第五章', 'B', '知识', False, False)
        schedule.sync_quest(math_id, '数学刷题（委托改名）', '第五章')
        titles = {p['id']: p['title'] for p in schedule.day(date)['plans']}
        assert titles[first['id']] == '数学刷题（委托改名）'

        # 自定义计划编辑不会影响任何委托
        schedule.update(night['id'], SchedulePlanUpdate(title='夜间拉伸', content='放松肩颈', start='22:00', end='23:00'))
        assert [q['title'] for q in quests.list(date)] == ['英语精读', '数学刷题（委托改名）']

        # 周视图按 4 小时分段，并标出今天
        week = schedule.week(date)
        assert week['week_start'] == '2026-09-07' and week['week_end'] == '2026-09-13'
        monday = week['days'][0]
        assert monday['date'] == date and monday['plan_count'] == 3
        bucket_titles = {b['name']: [p['title'] for p in b['plans']] for b in monday['buckets']}
        assert bucket_titles['清晨'] == [] and bucket_titles['深夜'] == []
        assert bucket_titles['上午'] == ['数学刷题（委托改名）', '英语精读']
        assert bucket_titles['夜晚'] == ['夜间拉伸']
        assert [d['is_today'] for d in week['days']].count(True) <= 1

        # 完成委托后颜色切换为“已完成”
        quests.set_completed(english_id, True)
        finished = [p for p in schedule.day(date)['plans'] if p['id'] == second['id']][0]
        assert finished['completed'] is True and finished['color_key'] == 'quest-done'

        # 删除委托：计划保留内容但解除绑定，转为自定义计划
        quests.delete(english_id)
        orphan = [p for p in schedule.day(date)['plans'] if p['id'] == second['id']][0]
        assert orphan['kind'] == 'free' and orphan['quest_id'] is None
        assert orphan['title'] == '英语精读'

        # 非法输入
        for bad_payload in (
            SchedulePlanCreate(plan_date=date, title='倒挂', start='10:00', end='09:00'),
            SchedulePlanCreate(plan_date=date, title='', start='10:00', end='11:00'),
            SchedulePlanCreate(plan_date=date, title='太短', start='10:00', end='10:03'),
            SchedulePlanCreate(plan_date=date, title='缺委托', start='10:00', end='11:00', quest_id=999999),
        ):
            try:
                schedule.create(bad_payload)
                raise AssertionError('非法计划应该被拒绝')
            except ValueError:
                pass


def regression_test_schedule_carry_over_and_delete():
    from app.api.schemas import SchedulePlanCreate
    from app.services.schedule_service import ScheduleService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Database(Path(tmp) / 'schedule-carry.db')
        quests = DailyQuestService(db)
        schedule = ScheduleService(db)

        carried_id = quests.create('未完成委托', '', 'A', '测试', False, '2026-09-07')
        plan = schedule.create(SchedulePlanCreate(plan_date='2026-09-07', start='14:00', end='16:00', quest_id=carried_id))

        # 日终结算后未完成委托顺延到次日，绑定计划一起移动
        SettlementService(db).settle_day('2026-09-07')
        moved = schedule.day('2026-09-08')['plans']
        assert [p['id'] for p in moved] == [plan['id']]
        assert schedule.day('2026-09-07')['plans'] == []

        # 删除计划只影响时间轴
        schedule.delete(plan['id'])
        assert schedule.day('2026-09-08')['plans'] == []
        assert len(quests.list('2026-09-08')) == 1

        try:
            schedule.delete(plan['id'])
            raise AssertionError('重复删除应该被拒绝')
        except ValueError:
            pass


if __name__ == '__main__':
    smoke_test()
    regression_test_multiday_carry_over()
    regression_test_journal_fields()
    regression_test_quest_batch_actions()
    regression_test_legend_manual_confirmation()
    regression_test_schedule_time_offsets()
    regression_test_schedule_binding_and_views()
    regression_test_schedule_carry_over_and_delete()
    print('ok')