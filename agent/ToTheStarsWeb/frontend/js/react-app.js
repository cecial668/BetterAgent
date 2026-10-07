(function () {
  const h = React.createElement;
  const F = React.Fragment;

  const NAV = [
    ['today', '今日总览', '☀', '今天从哪里开始'],
    ['quests', '每日委托', '✦', '行动与推进'],
    ['schedule', '日程表', '▦', '把一天排进时间轴'],
    ['legends', '传说任务', '◆', '长期目标战役'],
    ['focus', '番茄钟', '⏱', '沉浸专注空间'],
    ['rewards', '奖励商店', '✧', '让积累被兑现'],
    ['states', '每日日记', '◐', '收藏真实生活'],
    ['stats', '统计复盘', '◈', '看见成长轨迹'],
    ['agent', 'AI 活动', '✳', '看见她做了什么'],
    ['settings', '假期/设置', '⚙', '节奏与系统'],
  ];

  const AGENT_ACTION_LABELS = {
    'quest.create': '新增委托',
    'quest.update': '修改委托',
    'quest.complete': '更新完成状态',
    'quest.delete': '删除委托',
    'quest.batch_complete': '批量完成委托',
    'quest.batch_delete': '批量删除委托',
    'schedule.create': '新增日程',
    'schedule.update': '修改日程',
    'schedule.delete': '删除日程',
    'legend.create': '新增传说任务',
    'legend.update': '修改传说任务',
    'legend.delete': '删除传说任务',
    'legend.complete': '完成传说任务',
    'legend.indicator.add': '新增传说任务指标',
    'legend.indicator.complete': '勾选传说任务指标',
    'state.save': '保存日记',
    'audit.undo': '撤销了一次操作',
  };

  const AGENT_TARGET_LABELS = {
    daily_quest: '每日委托',
    schedule_plan: '日程计划',
    legend_quest: '传说任务',
    legend_indicator: '传说指标',
    daily_state: '每日日记',
    agent_audit: 'AI 操作记录',
  };

  function agentActionLabel(entry) {
    return AGENT_ACTION_LABELS[entry.action] || entry.action || '未知操作';
  }

  function agentEntryDetail(entry) {
    const p = entry.params || {};
    switch (entry.action) {
      case 'quest.create':
        return [p.title, p.difficulty ? `难度 ${p.difficulty}` : '', p.is_required ? '必要委托' : '', p.assigned_date || ''].filter(Boolean).join(' · ');
      case 'quest.update':
        return p.title ? `改为「${p.title}」` : '更新内容';
      case 'quest.complete':
        return p.completed ? '标记为已完成' : '恢复为未完成';
      case 'quest.delete':
      case 'schedule.delete':
      case 'legend.delete':
        return '已删除（可撤销恢复）';
      case 'quest.batch_complete':
      case 'quest.batch_delete':
        return `共 ${(p.ids || []).length} 条`;
      case 'schedule.create':
      case 'schedule.update':
        return [p.start && p.end ? `${p.start}-${p.end}` : '', p.title || '', p.plan_date || ''].filter(Boolean).join(' · ');
      case 'legend.create':
      case 'legend.update':
      case 'legend.indicator.add':
        return p.title || '';
      case 'legend.indicator.complete':
        return p.completed ? '勾选' : '取消勾选';
      case 'state.save':
        return [p.journal_title ? `「${p.journal_title}」` : '', p.rating ? `评分 ${p.rating}/5` : ''].filter(Boolean).join(' · ');
      case 'audit.undo':
        return p.action ? `撤销了「${AGENT_ACTION_LABELS[p.action] || p.action}」` : '';
      default:
        return '';
    }
  }


  const api = {
    async request(method, url, body) {
      const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
      const opt = { method, headers: isForm ? {} : { 'Content-Type': 'application/json' } };
      if (body !== undefined) opt.body = isForm ? body : JSON.stringify(body);
      const res = await fetch(url, opt);
      let data = null;
      try { data = await res.json(); } catch { data = {}; }
      if (!res.ok) throw new Error(data.detail || data.message || '请求失败');
      return data;
    },
    get(url) { return this.request('GET', url); },
    post(url, body = {}) { return this.request('POST', url, body); },
    put(url, body = {}) { return this.request('PUT', url, body); },
    del(url) { return this.request('DELETE', url); },
    upload(url, form) { return this.request('POST', url, form); },
  };

  function isTruthy(v) { return v === true || v === 1 || v === '1' || v === 'true' || v === 'True'; }
  function n(v, d = 0) { const x = Number(v); return Number.isFinite(x) ? x : d; }
  function clamp(v, min, max) { v = Math.round(n(v, min)); return Math.max(min, Math.min(max, v)); }
  function formData(id) { const f = typeof id === 'string' ? document.getElementById(id) : id; return Object.fromEntries(new FormData(f).entries()); }
  function fmtPoints(v) { return n(v).toFixed(1); }
  function sameWallet(a, b) {
    if (!a || !b) return a === b;
    return n(a.practice_points) === n(b.practice_points) && n(a.growth_points) === n(b.growth_points);
  }
  function fmtDuration(seconds) {
    seconds = Math.max(0, Math.floor(n(seconds)));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hours) return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }
  function toLocalString(date) {
    const d = date instanceof Date ? date : new Date(date);
    const pad = (v) => String(v).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  function todayIso() {
    const d = new Date();
    const pad = (v) => String(v).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  function empty(text) { return h('div', { className: 'empty' }, text); }
  function badge(text, extra = '') { return h('span', { className: `badge ${extra}`.trim() }, text); }
  function shuffledMemoryItems(entries = []) {
    const items = entries.flatMap((entry) => (entry.image_urls || []).map((src, index) => ({ ...entry, memory_src: src, memory_index: index })));
    for (let i = items.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [items[i], items[j]] = [items[j], items[i]];
    }
    return items.slice(0, 10);
  }

  function Wallet({ wallet }) {
    wallet = wallet || {};
    return h('div', { className: 'wallet' },
      h('div', { className: 'wallet-card' }, h('span', null, '历练点池'), h('b', null, fmtPoints(wallet.practice_points))),
      h('div', { className: 'wallet-card' }, h('span', null, '成长点池'), h('b', null, fmtPoints(wallet.growth_points)))
    );
  }

  function Table({ rows = [], columns = [] }) {
    if (!rows.length) return empty('暂无数据');
    return h('div', { className: 'table-wrap' },
      h('table', null,
        h('thead', null, h('tr', null, columns.map((c) => h('th', { key: c.key }, c.label)))),
        h('tbody', null, rows.map((row, i) => h('tr', { key: i }, columns.map((c) => h('td', { key: c.key }, row[c.key] ?? '')))))
      )
    );
  }

  function LoadingPanel({ text = '加载中...' }) {
    return h('div', { className: 'panel loading-panel' }, h('div', { className: 'loading-orb' }), h('p', null, text));
  }

  function ErrorPanel({ title = '页面加载失败', error }) {
    return h('div', { className: 'panel error-panel' },
      h('h3', null, title),
      h('p', null, String(error?.message || error || '未知错误')),
      h('p', { className: 'muted' }, '请确认后端服务正在运行，或在浏览器开发者工具中查看接口错误。')
    );
  }

  function MemoryCarousel({ items = [], onOpen, onJournal }) {
    if (!items.length) return h('div', { className: 'memory-stage empty-memory-stage' },
      h('div', { className: 'memory-constellation', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i')),
      h('p', { className: 'eyebrow' }, 'MEMORY FILM · 记忆胶片'),
      h('h3', null, '日子被写下以后，才开始拥有回声'),
      h('p', null, '为日记添加照片，它们会在这里成为首页的流动背景。'),
      h('button', { className: 'ghost', onClick: onJournal }, '写下第一段影像')
    );
    const loop = [...items, ...items];
    return h('div', { className: 'memory-stage' },
      h('div', { className: 'memory-stage-head' }, h('div', null, h('p', { className: 'eyebrow' }, 'MEMORY FILM · 记忆胶片'), h('b', null, '从过去借来一点光')), h('span', null, `${items.length} 个片段`)),
      h('div', { className: 'memory-marquee' },
        h('div', { className: 'memory-marquee-track', style: { '--memory-duration': `${Math.max(26, items.length * 5)}s` } }, loop.map((item, index) => h('button', { key: `${item.date}-${item.memory_index}-${index}`, className: 'memory-frame', onClick: () => onOpen(item), 'aria-label': `打开 ${item.date} 的日记：${item.journal_title || '未命名的一天'}` },
          h('img', { src: item.memory_src, alt: item.journal_title || '日记照片', loading: index < 4 ? 'eager' : 'lazy' }),
          h('span', { className: 'memory-frame-shade' }),
          h('span', { className: 'memory-frame-copy' }, h('time', null, item.date || ''), h('b', null, item.journal_title || '未命名的一天'))
        )))
      ),
      h('p', { className: 'memory-stage-note' }, '照片随机编排并缓慢流动 · 点击走回那一天')
    );
  }

  function DataDisclosure({ eyebrow, title, summary, children, open = false }) {
    return h('details', { className: 'data-disclosure', open },
      h('summary', null,
        h('div', null, h('p', { className: 'eyebrow' }, eyebrow), h('h3', null, title), summary && h('span', null, summary)),
        h('i', { 'aria-hidden': 'true' }, '+')
      ),
      h('div', { className: 'data-disclosure-body' }, children)
    );
  }

  function QuestCard({ q, index = 0, fresh = false, editable, onComplete, onView, multiSelect = false, selected = false, onSelect }) {
    const done = isTruthy(q.is_completed);
    const rarity = String(q.difficulty || 'A').toLowerCase();
    let holdTimer = null;
    let activated = false;
    const stopHold = (button) => {
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = null;
      if (!activated && button) button.classList.remove('charging');
    };
    const startHold = (event) => {
      if (done || activated || !onComplete) return;
      if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
      if (event.type === 'keydown' && event.repeat) return;
      event.preventDefault();
      const button = event.currentTarget;
      button.classList.add('charging');
      button.closest('.quest')?.classList.add('ritual-arming');
      holdTimer = setTimeout(() => {
        activated = true;
        button.classList.remove('charging');
        button.classList.add('unsealed');
        const card = button.closest('.quest');
        card?.classList.remove('ritual-arming');
        card?.classList.add('ritual-completing');
        setTimeout(() => onComplete(q, true), 660);
      }, 950);
    };
    const cancelHold = (event) => {
      const button = event.currentTarget;
      stopHold(button);
      button.closest('.quest')?.classList.remove('ritual-arming');
    };
    const reopen = () => {
      if (!onComplete || n(q.banked_points) > 0) return;
      if (confirm('将这项委托重新设为未完成？')) onComplete(q, false);
    };
    const cls = `card quest reveal-card rarity-${rarity} ${done ? 'completed done-card' : ''} ${fresh ? 'slot-in' : ''} ${multiSelect ? 'multi-selectable' : ''} ${selected ? 'batch-selected' : ''}`;
    const toggleSelected = (event) => {
      if (!multiSelect || !onSelect) return;
      if (event?.target?.closest?.('button,input')) return;
      onSelect(q.id);
    };
    return h('article', { className: cls, 'data-completed': done ? '1' : '0', 'aria-selected': multiSelect ? (selected ? 'true' : 'false') : undefined, onClick: toggleSelected, style: { '--accent': q.difficulty_color || '#64748B', '--stagger': `${Math.min(index, 12) * 42}ms` } },
      h('div', { className: 'rarity' }),
      h('div', { className: 'quest-spark-field', 'aria-hidden': 'true' }, [0,1,2,3,4,5,6,7].map((i) => h('i', { key: i, style: { '--spark': i } }))),
      multiSelect && h('label', { className: 'quest-batch-check', onClick: (e) => e.stopPropagation() },
        h('input', { type: 'checkbox', checked: selected, onChange: () => onSelect?.(q.id), 'aria-label': `选择委托 ${q.title}` }),
        h('span', { 'aria-hidden': 'true' }, '✓')
      ),
      h('div', { className: 'quest-card-main' },
        h('div', { className: 'card-head quest-card-head' },
          h('div', null,
            h('div', { className: 'quest-kicker' },
              isTruthy(q.is_required) && h('span', { className: 'quest-essential' }, '核心'),
              h('span', null, q.category || '未分类')
            ),
            h('h3', null, q.title)
          ),
          h('strong', { className: 'quest-value' }, h('small', null, '+'), fmtPoints(q.points), h('span', null, '历练点'))
        ),
        !multiSelect && h('button', { type: 'button', className: 'quest-detail-button', onClick: () => onView?.(q, editable), 'aria-label': `查看${q.title}详情` },
          h('span', null, '查看详情'), h('b', { 'aria-hidden': 'true' }, '↗')
        )
      ),
      !multiSelect && h('div', { className: 'actions quest-actions' },
        h('div', { className: `quest-ritual ${done ? 'is-done' : ''}` },
          h('button', {
            type: 'button', className: 'quest-ritual-button',
            'aria-label': done ? '委托已完成' : '长按完成委托',
            title: done ? (n(q.banked_points) > 0 ? '已入池，不能撤销' : '点击可重新开启') : '长按约 1 秒完成委托',
            disabled: done && n(q.banked_points) > 0,
            onPointerDown: startHold, onPointerUp: cancelHold, onPointerLeave: cancelHold, onPointerCancel: cancelHold,
            onKeyDown: startHold, onKeyUp: cancelHold, onClick: done ? reopen : (e) => e.preventDefault()
          },
            h('span', { className: 'ritual-ring' }),
            h('span', { className: 'ritual-icon', 'aria-hidden': 'true' }, done ? '♛' : '♙'),
            h('span', { className: 'ritual-burst', 'aria-hidden': 'true' })
          ),
          h('span', { className: 'ritual-label' }, done ? (n(q.banked_points) > 0 ? '奖励已入池' : '委托已完成') : '长按解锁奖励')
        )
      )
    );
  }

  function DailyQuestProgress({ data }) {
    const condition = data?.condition || {};
    const total = Math.max(0, n(condition.total_points));
    const requiredDone = !!condition.required_all_done;
    const vacation = !!data?.is_vacation;
    const achieved = vacation ? total > 0 : total >= 4 && requiredDone;
    const coreFill = Math.min(4, Math.floor(total));
    const bonusFill = Math.min(6, Math.max(0, Math.floor(total) - 4));
    const remaining = Math.max(0, 4 - total);
    const statusTitle = vacation ? '假期节奏' : achieved ? '今日核心已达成' : requiredDone ? `还差 ${fmtPoints(remaining)} 点` : '必要委托待完成';
    const statusNote = vacation ? '假期日不强制四点，完成的行动仍会被记录。' : achieved ? `已完成 ${fmtPoints(total)} 点，继续行动将进入附加探索。` : '先点亮前四枚核心星标，再自由选择附加委托。';
    const cells = (count, filled, type) => Array.from({ length: count }, (_, i) => h('span', { key: `${type}-${i}`, className: `quest-progress-cell ${type} ${i < filled ? 'filled' : ''}` }, h('b', null, type === 'core' ? i + 1 : i + 5)));
    return h('section', { className: `quest-progress-panel ${achieved ? 'achieved' : ''} ${vacation ? 'vacation' : ''}` },
      h('div', { className: 'quest-progress-copy' },
        h('p', { className: 'eyebrow' }, 'DAILY MISSION · 今日推进'),
        h('div', { className: 'quest-progress-head' }, h('h3', null, '四点为锚，更多是远征'), h('strong', null, `${fmtPoints(total)} / 4.0`)),
        h('div', { className: 'quest-progress-labels' }, h('span', null, '核心目标 · 必须完成'), h('span', null, '附加探索 · 自由加码')),
        h('div', { className: 'quest-progress-track', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '10', 'aria-valuenow': Math.min(10, total) },
          h('div', { className: 'quest-progress-core' }, cells(4, coreFill, 'core')),
          h('div', { className: 'quest-progress-gate' }, h('span', null, '4'), h('small', null, '达成线')),
          h('div', { className: 'quest-progress-bonus' }, cells(6, bonusFill, 'bonus'))
        ),
        total > 10 && h('p', { className: 'quest-overflow' }, `远征额外 +${fmtPoints(total - 10)} 点`)
      ),
      h('aside', { className: 'quest-status-emblem' },
        h('div', { className: 'quest-status-orbit' }, h('span', null, achieved ? '✓' : vacation ? '☾' : '✦')),
        h('div', null, h('b', null, statusTitle), h('p', null, statusNote))
      )
    );
  }

  function LegendCard({ l, onCompleteIndicator, onConfirmComplete, onAddIndicator, onEdit, onDelete }) {
    const progress = l.progress || { done: 0, total: 0 };
    const done = l.status === 'completed' || l.status === '已完成' || isTruthy(l.points_awarded);
    const ready = !done && (isTruthy(l.ready_to_complete) || (n(progress.total) > 0 && n(progress.done) >= n(progress.total)));
    const pct = progress.total ? Math.round(n(progress.done) / n(progress.total) * 100) : 0;
    let holdTimer = null;
    let activated = false;
    const stopSealHold = (button) => {
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = null;
      if (!activated && button) button.classList.remove('charging');
    };
    const startSealHold = (event) => {
      if (!ready || done || activated || !onConfirmComplete) return;
      if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
      if (event.type === 'keydown' && event.repeat) return;
      event.preventDefault();
      const button = event.currentTarget;
      const card = button.closest('.legend-campaign');
      button.classList.add('charging');
      card?.classList.add('legend-seal-arming');
      holdTimer = setTimeout(() => {
        activated = true;
        button.classList.remove('charging');
        button.classList.add('unsealed');
        card?.classList.remove('legend-seal-arming');
        card?.classList.add('legend-finalizing');
        setTimeout(() => onConfirmComplete(l), 1040);
      }, 1350);
    };
    const cancelSealHold = (event) => {
      stopSealHold(event.currentTarget);
      event.currentTarget.closest('.legend-campaign')?.classList.remove('legend-seal-arming');
    };
    const checkpointState = done ? '战役已封存' : ready ? '全部指标已完成，最终封印已解除' : `完成其余 ${Math.max(0, n(progress.total) - n(progress.done))} 项后解除最终封印`;
    return h('article', { className: `card legend legend-campaign ${ready ? 'ready-to-seal' : ''} ${done ? 'completed done-card' : ''}`, 'data-completed': done ? '1' : '0', style: { '--legend-accent': l.difficulty_color || '#a855f7' } },
      h('div', { className: 'legend-ascension-field', 'aria-hidden': 'true' }, Array.from({ length: 18 }, (_, i) => h('i', { key: i, style: { '--star': i } }))),
      h('div', { className: 'legend-campaign-head' },
        h('div', { className: 'legend-rank-sigil' }, h('span', null, l.difficulty || 'A'), h('small', null, l.difficulty_name || '传说')),
        h('div', { className: 'legend-title-copy' }, h('p', { className: 'eyebrow' }, done ? 'CAMPAIGN COMPLETE' : ready ? 'FINAL SEAL UNLOCKED' : 'ACTIVE CAMPAIGN'), h('h3', null, l.title), h('p', { className: 'muted' }, l.content || '没有额外说明。')),
        h('strong', { className: 'legend-reward' }, h('small', null, '最终奖励'), `+${fmtPoints(l.growth_points)}`, h('span', null, '成长点'))
      ),
      h('div', { className: 'legend-route-meta' }, h('span', null, `截止 ${l.deadline || '-'}`), h('span', null, `剩余 ${l.remaining_days ?? '-'} 天`), h('b', null, `${pct}%`)),
      h('div', { className: 'legend-route' }, h('span', { style: { width: `${pct}%` } }), h('i', { style: { left: `${Math.max(2, Math.min(98, pct))}%` } }, '✦')),
      h('div', { className: 'indicator-list legend-checkpoints' }, (l.indicators || []).map((i, index) => {
        const idone = isTruthy(i.is_completed);
        return h('button', {
          key: i.id,
          type: 'button',
          className: `indicator legend-checkpoint-toggle ${idone ? 'done' : ''}`,
          disabled: done,
          role: 'switch',
          'aria-checked': idone ? 'true' : 'false',
          'aria-label': `${i.title}，当前${idone ? '已完成，点击可回退' : '未完成，点击标记完成'}`,
          onClick: () => onCompleteIndicator(i, !idone)
        },
          h('span', { className: 'checkpoint-number', 'aria-hidden': 'true' }, idone ? '✓' : String(index + 1).padStart(2, '0')),
          h('span', { className: 'checkpoint-copy' }, h('b', null, i.title), h('small', null, done ? '已随战役封存' : idone ? '已抵达 · 点击可撤回' : '尚未抵达 · 点击点亮')),
          h('span', { className: 'checkpoint-switch', 'aria-hidden': 'true' }, h('i'))
        );
      })),
      h('section', { className: `legend-final-seal ${done ? 'is-complete' : ready ? 'is-ready' : 'is-locked'}` },
        h('div', { className: 'legend-seal-copy' },
          h('p', { className: 'eyebrow' }, done ? 'LEGEND RECORDED' : ready ? 'FINAL ASCENSION · 最终确认' : 'FINAL SEAL · 最终封印'),
          h('h4', null, done ? '这段旅程已写入星图' : ready ? '全部星标已归位，等待你的最终确认' : '完成全部分指标后解锁'),
          h('p', null, checkpointState)
        ),
        h('div', { className: 'legend-seal-ritual' },
          h('button', {
            type: 'button',
            className: 'legend-seal-button',
            disabled: !ready || done,
            'aria-label': done ? '传说任务已完成' : ready ? '长按确认完成传说任务' : '传说任务指标尚未全部完成',
            title: done ? '传说任务已完成' : ready ? '长按约 1.4 秒完成最终确认' : '完成全部分指标后解锁',
            onPointerDown: startSealHold, onPointerUp: cancelSealHold, onPointerLeave: cancelSealHold, onPointerCancel: cancelSealHold,
            onKeyDown: startSealHold, onKeyUp: cancelSealHold,
            onClick: (event) => event.preventDefault()
          },
            h('span', { className: 'legend-seal-orbit outer', 'aria-hidden': 'true' }),
            h('span', { className: 'legend-seal-orbit inner', 'aria-hidden': 'true' }),
            h('span', { className: 'legend-seal-core', 'aria-hidden': 'true' }, done ? '✦' : ready ? '◆' : '⌁'),
            h('span', { className: 'legend-seal-flare', 'aria-hidden': 'true' })
          ),
          h('span', null, done ? '传说已完成' : ready ? '长按完成最终升格' : `${progress.done}/${progress.total} · 封印中`)
        )
      ),
      h('div', { className: 'actions legend-campaign-actions' },
        h('span', null, `已抵达 ${progress.done}/${progress.total} 个检查点`),
        !done && h('button', { className: 'small ghost', onClick: () => onAddIndicator(l) }, '＋ 检查点'),
        !done && h('button', { className: 'small ghost', onClick: () => onEdit(l) }, '编辑'),
        h('button', { className: 'small danger ghost', onClick: () => onDelete(l) }, '归档')
      )
    );
  }

  function rewardProgressInfo(r, wallet) {
    const price = n(r.price);
    const balance = r.point_type === 'growth' ? n(wallet?.growth_points) : n(wallet?.practice_points);
    const rawPercent = price <= 0 ? 100 : (balance / price) * 100;
    const percent = Math.max(0, Math.min(100, rawPercent));
    const hue = Math.round(percent * 1.2);
    return { price, balance, percent, barColor: `hsl(${hue}, 78%, 52%)`, needMore: Math.max(price - balance, 0) };
  }
  function rewardSortGroup(r) {
    const stock = n(r.stock);
    if (stock <= 0 || r.display_status === '售空' || r.status === 'sold_out') return 3;
    if (r.affordable) return 1;
    return 2;
  }

  function RewardCard({ r, wallet, onBuy, onEdit, onDelete }) {
    const info = rewardProgressInfo(r, wallet);
    const pointLabel = r.point_type === 'growth' ? '成长点' : '历练点';
    const statusClass = r.display_status === '售空' || n(r.stock) <= 0 ? 'soldout' : r.affordable ? 'ok' : 'no';
    const progressText = statusClass === 'soldout' ? '该奖励已售空' : r.affordable ? '已满足兑换条件，购买后进入待出库' : `还差 ${info.needMore.toFixed(1)} ${pointLabel}`;
    return h('article', { className: `card reward reward-card reward-ticket ${statusClass}` },
      h('div', { className: 'reward-ticket-top' },
        h('div', { className: 'reward-glyph', 'aria-hidden': 'true' }, statusClass === 'ok' ? '✦' : statusClass === 'soldout' ? '—' : '◇'),
        h('div', { className: 'reward-title-block' }, h('p', { className: 'eyebrow' }, pointLabel === '成长点' ? 'GROWTH REWARD' : 'PRACTICE REWARD'), h('h3', null, r.name)),
        h('span', { className: `reward-status ${statusClass}` }, r.display_status)
      ),
      h('p', { className: 'reward-summary' }, r.content || '一份等待被兑现的奖励。'),
      h('div', { className: 'reward-price-lockup' },
        h('span', null, '兑换价格'),
        h('strong', null, info.price.toFixed(1)),
        h('small', null, pointLabel)
      ),
      h('div', { className: 'reward-progress-compact' },
        h('div', { className: 'reward-progress-top' }, h('span', null, `余额 ${info.balance.toFixed(1)}`), h('strong', null, `${info.percent.toFixed(0)}%`)),
        h('div', { className: 'reward-progress-track' }, h('div', { className: 'reward-progress-fill', style: { width: `${info.percent}%`, background: info.barColor, boxShadow: `0 0 16px ${info.barColor}` } })),
        h('div', { className: 'reward-progress-note' }, progressText)
      ),
      h('div', { className: 'reward-ticket-footer' },
        h('span', { className: 'reward-stock' }, `库存 ${n(r.stock)}`),
        h('div', { className: 'actions' },
          h('button', { className: 'reward-buy-button', onClick: () => onBuy(r), disabled: !r.affordable }, r.affordable ? '兑换奖励' : '点数不足'),
          h('button', { className: 'icon-button ghost', onClick: () => onEdit(r), title: '编辑奖励', 'aria-label': '编辑奖励' }, '✎'),
          h('button', { className: 'icon-button danger ghost', onClick: () => onDelete(r), title: '删除奖励', 'aria-label': '删除奖励' }, '×')
        )
      )
    );
  }

  function PurchaseCard({ p, onOutbound }) {
    const shipped = p.outbound_status === 'shipped';
    const pointLabel = p.point_type === 'growth' ? '成长点' : '历练点';
    return h('article', { className: `card reward reward-card purchase-card ${shipped ? 'shipped' : 'pending'}` },
      h('div', { className: 'card-head' },
        h('div', null, h('h3', null, p.display_name || p.reward_name || '已购买奖励'), h('p', { className: 'muted' }, p.display_content || p.reward_content || '没有描述')),
        badge(p.outbound_status_label || (shipped ? '已出库' : '待出库'), shipped ? '' : 'gold')
      ),
      h('div', { className: 'reward-price-row' }, h('span', null, '购买时间'), h('strong', null, p.purchased_at || '-')),
      h('div', { className: 'reward-price-row' }, h('span', null, '消耗'), h('strong', null, `${fmtPoints(p.price)} ${pointLabel}`)),
      h('div', { className: 'reward-price-row' }, h('span', null, '购买后余额'), h('strong', null, `${fmtPoints(p.balance_after)} ${pointLabel}`)),
      h('div', { className: 'reward-stock-row' }, h('span', null, '购买后库存'), h('strong', null, n(p.stock_after))),
      shipped ? [h('div', { className: 'outbound-seal', key: 'seal' }, '已出库'), h('p', { className: 'muted', key: 't' }, `出库时间：${p.outbound_at || '-'}`)] :
        h('div', { className: 'actions' }, h('button', { onClick: () => onOutbound(p) }, '确认出库'))
    );
  }

  function FocusChart({ daily = [] }) {
    if (!daily.length) return empty('暂无专注统计数据');
    const max = Math.max(...daily.map((d) => n(d.seconds)), 1);
    return h('div', { className: 'focus-chart', 'aria-label': '每日专注时长图表' }, daily.map((d) => {
      const seconds = n(d.seconds);
      const height = seconds ? Math.max(8, Math.round(seconds / max * 100)) : 4;
      const label = String(d.date || '').slice(5);
      return h('div', { className: 'focus-chart-item', key: d.date, title: `${d.date || ''} · ${d.label || fmtDuration(seconds)}` },
        h('div', { className: 'focus-bar-wrap' }, h('span', { className: 'focus-bar', style: { height: `${height}%` } })),
        h('small', null, label)
      );
    }));
  }

  function diaryMoodLabel(value, kind = 'energy') {
    const labels = kind === 'social' ? ['想独处', '安静', '平衡', '愿意交流', '连接充足'] : ['见底', '偏低', '平稳', '充沛', '闪耀'];
    return labels[clamp(n(value) + 2, 0, 4)];
  }

  function JournalCard({ entry, index = 0, onOpen }) {
    const images = entry.image_urls || [];
    const cover = images[0];
    return h('article', { className: 'journal-card reveal-card', style: { '--stagger': `${Math.min(index, 16) * 48}ms` }, onClick: () => onOpen(entry) },
      h('div', { className: `journal-cover ${cover ? 'has-image' : ''}` },
        cover ? h('img', { src: cover, alt: entry.journal_title || '日记图片', loading: 'lazy' }) : h('div', { className: 'journal-placeholder' }, h('span', null, '✦'), h('small', null, '这一天没有照片')),
        images.length > 1 && h('span', { className: 'journal-photo-count' }, `${images.length} 张`)
      ),
      h('div', { className: 'journal-card-body' },
        h('time', null, entry.date || ''),
        h('h3', null, entry.journal_title || '未命名的一天'),
        h('p', null, entry.review_text || '这一天只留下了心情坐标。'),
        h('div', { className: 'journal-card-meta' }, h('span', null, `${'★'.repeat(clamp(entry.rating || 3, 1, 5))}`), h('span', null, diaryMoodLabel(entry.energy)))
      )
    );
  }

  class StarApp extends React.Component {
    constructor(props) {
      super(props);
      this.state = {
        page: 'today',
        boot: null,
        wallet: null,
        loading: true,
        error: null,
        pageData: null,
        modal: null,
        toasts: [],
        agentFilter: 'all',
      };
      this.rewardTab = 'shop';
      this.todayMemoryItems = [];
      this.journalFiles = [];
      this.journalPreviewUrls = [];
      this.journalDraft = null;
      this.recentlyCreatedQuestId = null;
      this.questMultiSelect = false;
      this.selectedQuestIds = new Set();
      this.batchQuestBusy = false;
      this.focusStorageKey = 'to-the-stars-focus-timer-v1';
      this.focus = {
        mode: 'idle', plannedSeconds: 30 * 60, remainingSeconds: 30 * 60, accumulatedSeconds: 0,
        segmentStartedMs: null, startedAt: null, endedAt: null, todayStoredSeconds: 0,
        sessions: [], categories: [], presets: [15, 25, 30, 45, 60], category: '知识', description: '', loadedOnce: false, saving: false,
      };
      this.scheduleView = 'week';
      this.scheduleWeekDate = null;
      this.scheduleDate = null;
      this.rolloverTimer = null;
      this.focusTimer = null;
      this.focusLastPaintSecond = null;
      this.focusLastPersistSecond = null;
    }

    componentDidMount() {
      this.init();
      window.addEventListener('beforeunload', (e) => {
        if (['running', 'paused', 'finished'].includes(this.focus.mode)) {
          this.persistFocus();
          e.preventDefault();
          e.returnValue = '';
        }
      });
    }

    async init() {
      try {
        const boot = await api.get('/api/bootstrap');
        this.setState({ boot, wallet: boot.wallet });
        await this.loadPage('today');
        this.startRolloverPolling();
      } catch (err) {
        this.setState({ loading: false, error: err });
        this.toast(err.message || '启动失败', 'error');
      }
    }

    toast(msg, type = 'info') {
      const root = document.getElementById('toast-root');
      if (!root) return;
      const item = document.createElement('div');
      item.className = `toast ${type || 'info'}`;
      item.textContent = msg;
      root.appendChild(item);
      setTimeout(() => {
        item.classList.add('leaving');
        setTimeout(() => item.remove(), 220);
      }, 3200);
    }

    async safe(fn, okText) {
      try {
        const result = await fn();
        if (okText) this.toast(okText);
        return result;
      } catch (err) {
        this.toast(err.message || '操作失败', 'error');
        throw err;
      }
    }

    async refreshWallet() {
      const wallet = await api.get('/api/wallet');
      this.updateWallet(wallet);
      return wallet;
    }

    updateWallet(wallet) {
      if (!wallet || sameWallet(wallet, this.state.wallet)) return false;
      this.setState({ wallet });
      return true;
    }

    async loadPage(page = this.state.page) {
      if (page !== this.state.page && this.questMultiSelect) this.exitQuestMultiSelect(false);
      const switchingPage = page !== this.state.page || !this.state.pageData;
      if (switchingPage) this.setState({ page, loading: true, error: null });
      try {
        const data = await this.fetchPageData(page);
        this.setState({ page, pageData: data, loading: false, error: null });
      } catch (err) {
        this.setState({ page, pageData: null, loading: false, error: err });
        this.toast(err.message || '页面加载失败', 'error');
      }
    }

    async fetchPageData(page) {
      if (page === 'today') {
        const [data, recent] = await Promise.all([api.get('/api/quests/today'), api.get('/api/states/recent?limit=80')]);
        this.updateWallet(data.wallet);
        const signature = (recent || []).map((entry) => `${entry.date}:${(entry.image_urls || []).join(',')}`).join('|');
        if (!this.todayMemoryItems.length || this.todayMemorySignature !== signature) {
          this.todayMemoryItems = shuffledMemoryItems(recent || []);
          this.todayMemorySignature = signature;
        }
        return { ...data, recent_journals: recent || [], memory_items: this.todayMemoryItems };
      }
      if (page === 'quests') return api.get('/api/quests/today');
      if (page === 'schedule') {
        const anchor = this.scheduleWeekDate || this.state.boot?.date || todayIso();
        const week = await api.get(`/api/schedule/week?date=${anchor}`);
        this.scheduleWeekDate = week.week_start;
        let day = null;
        if (this.scheduleView === 'day') {
          day = await api.get(`/api/schedule/day?date=${this.scheduleDate || week.today}`);
          this.scheduleDate = day.date;
        }
        return { ...week, day };
      }
      if (page === 'legends') return api.get('/api/legends');
      if (page === 'focus') {
        const data = await api.get('/api/focus/today');
        this.applyFocusToday(data);
        return data;
      }
      if (page === 'rewards') {
        const [rewards, purchases, wallet] = await Promise.all([api.get('/api/rewards'), api.get('/api/rewards/purchases'), api.get('/api/wallet')]);
        this.updateWallet(wallet);
        return { rewards, purchases, wallet };
      }
      if (page === 'states') {
        const [state, recent] = await Promise.all([api.get('/api/states/today'), api.get('/api/states/recent?limit=120')]);
        return { state, recent, constants: this.state.boot?.constants || {} };
      }
      if (page === 'stats') {
        const [sum, tx, st, sett, cat, leg, focus] = await Promise.all([
          api.get('/api/stats/summary'), api.get('/api/stats/transactions'), api.get('/api/stats/states'),
          api.get('/api/stats/settlements'), api.get('/api/stats/quests-by-category'), api.get('/api/stats/legend-progress'), api.get('/api/stats/focus?days=14'),
        ]);
        return { sum, tx, st, sett, cat, leg, focus };
      }
      if (page === 'agent') return api.get('/api/agent/audit?limit=120');
      if (page === 'settings') {
        const [boot, vacations] = await Promise.all([api.get('/api/bootstrap'), api.get('/api/vacations')]);
        const nextState = { boot };
        if (!sameWallet(boot.wallet, this.state.wallet)) nextState.wallet = boot.wallet;
        this.setState(nextState);
        return { boot, vacations };
      }
      return null;
    }

    startRolloverPolling() {
      if (this.rolloverTimer) clearInterval(this.rolloverTimer);
      this.rolloverTimer = setInterval(() => this.checkRollover(), 90000);
    }

    async checkRollover() {
      try {
        const data = await api.get('/api/rollover-status');
        this.updateWallet(data.wallet);
        if (data.results?.length) {
          this.showSettlementResults('凌晨 4 点日终结算完成', data.results);
          const fresh = await this.fetchPageData(this.state.page || 'today');
          this.setState({ pageData: fresh, loading: false, error: null });
        }
      } catch (err) {
        console.warn('rollover check failed', err);
      }
    }

    showSettlementResults(title, results) {
      if (!results?.length) return;
      this.setState({ modal: {
        title,
        body: h('div', { className: 'stack' }, results.map((r, i) => h('div', { className: 'panel mini-panel', key: i },
          h('h4', null, `${r.date || ''} · ${r.day_title || '日终结算'}`),
          h('p', null, `新入池：${fmtPoints(r.points_banked)} 点；状态奖励：${fmtPoints(r.state_bonus)} 点。`),
          h('p', { className: 'muted' }, `完成委托：${(r.completed_titles || []).join('、') || '无'}`),
          h('p', { className: 'muted' }, `顺延委托：${(r.carried_titles || []).join('、') || '无'}`),
          r.explain && h('p', { className: 'muted' }, r.explain)
        ))),
        actions: h('button', { className: 'primary', onClick: () => this.closeModal() }, '知道了')
      }});
    }

    closeModal() { this.setState({ modal: null }); }

    async shutdown() {
      await this.safe(() => api.post('/api/shutdown'), '已记录关闭时间，可以直接关闭窗口。');
    }

    async toggleQuest(q, completed, pageName = this.state.page) {
      await this.safe(async () => {
        const res = await api.post(`/api/quests/${q.id}/complete`, { completed });
        if (res.wallet) this.setState({ wallet: res.wallet });
        if (pageName === 'today') {
          const current = this.state.pageData || {};
          this.setState({ pageData: { ...current, quests: res.quests || current.quests || [], condition: res.condition || current.condition || {} } });
        } else {
          const current = this.state.pageData || {};
          this.setState({ pageData: { ...current, quests: res.quests || current.quests || [], condition: res.condition || current.condition || {} } });
        }
      }, completed ? '委托完成，奖励已解锁' : '委托已重新开启');
    }

    async deleteQuest(q) {
      if (!confirm('删除前会写入历史记录，确定删除？')) return;
      await this.safe(async () => { await api.del(`/api/quests/${q.id}`); await this.loadPage(this.state.page); }, '已删除');
    }

    toggleQuestMultiSelect() {
      if (this.batchQuestBusy) return;
      if (this.questMultiSelect) this.exitQuestMultiSelect(true);
      else {
        this.questMultiSelect = true;
        this.selectedQuestIds = new Set();
        this.forceUpdate();
      }
    }

    exitQuestMultiSelect(render = true) {
      if (!this.questMultiSelect && !this.selectedQuestIds.size) return;
      this.questMultiSelect = false;
      this.selectedQuestIds = new Set();
      if (render) this.forceUpdate();
    }

    toggleQuestSelection(qid) {
      if (!this.questMultiSelect || this.batchQuestBusy) return;
      const next = new Set(this.selectedQuestIds);
      if (next.has(qid)) next.delete(qid); else next.add(qid);
      this.selectedQuestIds = next;
      this.forceUpdate();
    }

    selectAllQuests(rows = []) {
      if (this.batchQuestBusy) return;
      const allIds = rows.map((q) => q.id);
      this.selectedQuestIds = this.selectedQuestIds.size === allIds.length ? new Set() : new Set(allIds);
      this.forceUpdate();
    }

    async batchCompleteQuests() {
      const ids = [...this.selectedQuestIds];
      if (!ids.length || this.batchQuestBusy) return;
      this.batchQuestBusy = true;
      this.forceUpdate();
      document.querySelectorAll('.quest.batch-selected').forEach((card, index) => {
        card.style.setProperty('--batch-delay', `${Math.min(index, 12) * 70}ms`);
        card.classList.add('batch-ritual-completing');
      });
      const ritualDuration = 1120 + Math.min(Math.max(ids.length - 1, 0), 12) * 70;
      await new Promise((resolve) => setTimeout(resolve, ritualDuration));
      try {
        const result = await api.post('/api/quests/batch/complete', { ids });
        this.updateWallet(result.wallet);
        const current = this.state.pageData || {};
        this.questMultiSelect = false;
        this.selectedQuestIds = new Set();
        this.setState({ pageData: { ...current, ...result } });
        this.toast(`星阵共鸣完成：${ids.length} 项委托已点亮。`);
      } catch (err) {
        document.querySelectorAll('.quest.batch-ritual-completing').forEach((card) => card.classList.remove('batch-ritual-completing'));
        this.toast(err.message || '批量完成失败', 'error');
      } finally {
        this.batchQuestBusy = false;
        this.forceUpdate();
      }
    }

    async batchDeleteQuests() {
      const ids = [...this.selectedQuestIds];
      if (!ids.length || this.batchQuestBusy) return;
      if (!confirm(`确定删除选中的 ${ids.length} 项委托？已获得及已入池的历练点不会被扣除。`)) return;
      this.batchQuestBusy = true;
      this.forceUpdate();
      try {
        const result = await api.post('/api/quests/batch/delete', { ids });
        this.updateWallet(result.wallet);
        const current = this.state.pageData || {};
        this.questMultiSelect = false;
        this.selectedQuestIds = new Set();
        this.setState({ pageData: { ...current, ...result } });
        this.toast(`已删除 ${ids.length} 项委托，历练点保持不变。`);
      } catch (err) {
        this.toast(err.message || '批量删除失败', 'error');
      } finally {
        this.batchQuestBusy = false;
        this.forceUpdate();
      }
    }

    renderQuestBatchBar(rows = []) {
      if (!this.questMultiSelect) return null;
      const count = this.selectedQuestIds.size;
      const allSelected = !!rows.length && count === rows.length;
      return h('aside', { className: `quest-batch-bar ${count ? 'has-selection' : ''} ${this.batchQuestBusy ? 'busy' : ''}` },
        h('div', { className: 'quest-batch-summary' },
          h('div', { className: 'quest-batch-constellation', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('span', null, count)),
          h('div', null, h('b', null, count ? `已编入 ${count} 项委托` : '选择要编入星阵的委托'), h('p', null, count ? '可以统一完成或删除；删除不会回滚历练点。' : '点击卡片或左上角勾选框进行选择。'))
        ),
        h('div', { className: 'quest-batch-actions' },
          h('button', { className: 'ghost batch-select-all', onClick: () => this.selectAllQuests(rows), disabled: this.batchQuestBusy }, allSelected ? '取消全选' : '全部选择'),
          h('button', { className: 'danger ghost batch-delete-button', onClick: () => this.batchDeleteQuests(), disabled: !count || this.batchQuestBusy }, '批量删除'),
          h('button', { className: 'batch-complete-button', onClick: () => this.batchCompleteQuests(), disabled: !count || this.batchQuestBusy },
            h('span', { className: 'batch-complete-orbit', 'aria-hidden': 'true' }),
            h('span', { className: 'batch-complete-icon', 'aria-hidden': 'true' }, '✦'),
            h('span', null, this.batchQuestBusy ? '星阵共鸣中' : '全部完成')
          )
        )
      );
    }

    openQuestDetail(q, editable = false) {
      const done = isTruthy(q.is_completed);
      this.setState({ modal: {
        title: q.title || '委托详情',
        body: h('article', { className: 'quest-detail-sheet', style: { '--accent': q.difficulty_color || '#64748B' } },
          h('div', { className: 'quest-detail-hero' },
            h('div', { className: 'quest-detail-rank' }, h('span', null, q.difficulty || 'A'), h('small', null, q.difficulty_name || '日常')),
            h('div', null, h('p', { className: 'eyebrow' }, done ? 'MISSION COMPLETE' : 'MISSION BRIEFING'), h('h3', null, `+${fmtPoints(q.points)} 历练点`), h('p', { className: 'muted' }, done ? '该委托已经完成。' : '完成后计入今日推进，日终结算后进入点数池。'))
          ),
          h('dl', { className: 'quest-detail-list' },
            h('div', null, h('dt', null, '任务说明'), h('dd', null, q.description || '没有额外说明。')),
            h('div', null, h('dt', null, '分类'), h('dd', null, q.category || '未分类')),
            h('div', null, h('dt', null, '性质'), h('dd', null, `${isTruthy(q.is_required) ? '必要委托' : '自由委托'}${isTruthy(q.is_recurring) ? ' · 日常委托' : ''}`)),
            h('div', null, h('dt', null, '奖励状态'), h('dd', null, done ? (n(q.banked_points) > 0 ? `已入池 ${fmtPoints(q.banked_points)} 点` : '已完成，等待结算') : '尚未完成'))
          )
        ),
        actions: h(F, null,
          editable && h('button', { className: 'danger ghost', onClick: () => { this.closeModal(); this.deleteQuest(q); } }, '删除委托'),
          editable && h('button', { className: 'ghost', onClick: () => this.openQuestForm(q) }, '编辑委托'),
          h('button', { onClick: () => this.closeModal() }, '返回任务板')
        )
      }});
    }

    openQuestForm(q = null) {
      const c = this.state.boot?.constants || {};
      const diff = c.difficulties || {};
      const baseCats = c.categories || [];
      const currentCategory = q?.category || baseCats[0] || '未分类';
      const categories = [...baseCats];
      if (currentCategory && !categories.includes(currentCategory)) categories.unshift(currentCategory);
      this.setState({ modal: {
        title: q ? '编辑委托' : '新建每日委托',
        body: h('form', { id: 'quest-form', className: 'form' },
          h('label', null, '名称', h('input', { name: 'title', defaultValue: q?.title || '', required: true })),
          h('label', null, '描述', h('textarea', { name: 'description', defaultValue: q?.description || '' })),
          h('label', null, '难度', h('select', { name: 'difficulty', defaultValue: q?.difficulty || Object.keys(diff)[0] || 'A' },
            Object.keys(diff).map((k) => h('option', { key: k, value: k, selected: (q?.difficulty || 'A') === k }, `${k} · ${diff[k].name}（${diff[k].points}点）`))
          )),
          h('label', null, '分类', h('select', { name: 'category_select', defaultValue: currentCategory },
            categories.map((cat) => h('option', { key: cat, value: cat, selected: currentCategory === cat }, cat)),
            h('option', { value: '__custom__' }, '自定义分类...')
          )),
          h('label', null, '自定义分类名称（选择“自定义分类”时填写）', h('input', { name: 'category_custom', placeholder: '例如：雅思、论文、健身、申请材料' })),
          h('label', { className: 'checkbox-line' }, h('input', { type: 'checkbox', name: 'is_required', defaultChecked: !!q?.is_required }), h('span', null, h('b', null, '必要委托'), h('small', null, '普通日必须完成，否则当天每日委托判定失败'))),
          h('label', { className: 'checkbox-line' }, h('input', { type: 'checkbox', name: 'is_recurring', defaultChecked: !!q?.is_recurring }), h('span', null, h('b', null, '日常委托'), h('small', null, '完成并日终结算后，第二天会自动刷新一份未完成的新委托')))
        ),
        actions: h('button', { onClick: () => this.saveQuest(q) }, '保存')
      }});
    }

    async saveQuest(q) {
      const f = document.getElementById('quest-form');
      const data = formData(f);
      let category = data.category_select;
      if (category === '__custom__') category = (data.category_custom || '').trim();
      if (!category) { this.toast('请填写分类名称', 'error'); return; }
      data.category = category;
      data.is_required = f.querySelector('[name="is_required"]').checked;
      data.is_recurring = f.querySelector('[name="is_recurring"]').checked;
      delete data.category_select; delete data.category_custom;
      await this.safe(async () => {
        if (q) await api.put(`/api/quests/${q.id}`, data);
        else {
          const result = await api.post('/api/quests', data);
          this.recentlyCreatedQuestId = result.id;
          setTimeout(() => { this.recentlyCreatedQuestId = null; }, 1200);
        }
        this.closeModal();
        await this.loadPage(this.state.page);
      }, '委托已保存');
    }

    async manualSettlement() {
      await this.safe(async () => {
        const r = await api.post('/api/settlements/manual', {});
        if (r.wallet) this.setState({ wallet: r.wallet });
        this.setState({ modal: { title: '普通结算结果', body: h('div', null,
          h('p', null, r.explain), h('p', null, '本次入池：', h('b', null, fmtPoints(r.points_banked)), ' 点'),
          h('p', null, `当前余额：${fmtPoints(r.wallet?.practice_points)} 历练点`)
        ), actions: h('button', { onClick: () => this.closeModal() }, '知道了') } });
        await this.loadPage('today');
      });
    }

    async endSettlement() {
      await this.safe(async () => {
        const r = await api.post('/api/settlements/end', {});
        if (r.wallet) this.setState({ wallet: r.wallet });
        this.setState({ modal: { title: '日终结算', body: h('div', null,
          h('p', null, r.explain),
          h('p', null, `完成委托：${(r.completed_titles || []).join('、') || '无'}`),
          h('p', null, `顺延委托：${(r.carried_titles || []).join('、') || '无'}`)
        ), actions: h('button', { onClick: () => this.closeModal() }, '知道了') } });
        await this.loadPage('today');
      });
    }

    openLegendForm(l = null) {
      const diff = this.state.boot?.constants?.legend_difficulties || {};
      this.setState({ modal: {
        title: l ? '编辑传说任务' : '创建传说任务',
        body: h('form', { id: 'legend-form', className: 'form' },
          h('label', null, '名称', h('input', { name: 'title', defaultValue: l?.title || '', required: true })),
          h('label', null, '内容', h('textarea', { name: 'content', defaultValue: l?.content || '' })),
          h('label', null, '难度', h('select', { name: 'difficulty', defaultValue: l?.difficulty || Object.keys(diff)[0] || 'A' },
            Object.keys(diff).map((k) => h('option', { key: k, value: k, selected: (l?.difficulty || 'A') === k }, `${k} · ${diff[k].name}（${diff[k].points}点）`))
          ),
          ),
          h('label', null, '截止日期', h('input', { type: 'date', name: 'deadline', defaultValue: l?.deadline || '', required: true })),
          !l && h('label', null, '初始指标（每行一个）', h('textarea', { name: 'indicators' }))
        ),
        actions: h('button', { onClick: () => this.saveLegend(l) }, '保存')
      }});
    }

    async saveLegend(l) {
      const data = formData('legend-form');
      if (!l) data.indicators = (data.indicators || '').split('\n').map((x) => x.trim()).filter(Boolean);
      await this.safe(async () => {
        if (l) await api.put(`/api/legends/${l.id}`, data);
        else await api.post('/api/legends', data);
        this.closeModal();
        await this.loadPage('legends');
      }, '传说任务已保存');
    }

    openIndicatorForm(l) {
      this.setState({ modal: {
        title: '新增指标',
        body: h('form', { id: 'indicator-form', className: 'form' },
          h('label', null, '指标名称', h('input', { name: 'title', required: true })),
          h('label', null, '指标描述', h('textarea', { name: 'description' }))
        ),
        actions: h('button', { onClick: () => this.saveIndicator(l) }, '保存')
      }});
    }

    async saveIndicator(l) {
      const data = formData('indicator-form');
      await this.safe(async () => { await api.post(`/api/legends/${l.id}/indicators`, data); this.closeModal(); await this.loadPage('legends'); }, '指标已新增');
    }

    async completeIndicator(i, completed) {
      await this.safe(async () => {
        const r = await api.post(`/api/legends/indicators/${i.id}/complete`, { completed });
        const next = { pageData: r.legends || this.state.pageData };
        if (r.wallet && !sameWallet(r.wallet, this.state.wallet)) next.wallet = r.wallet;
        this.setState(next);
      }, completed ? '检查点已点亮' : '检查点已回退');
    }

    async confirmLegendComplete(l) {
      await this.safe(async () => {
        const r = await api.post(`/api/legends/${l.id}/complete`);
        const next = { pageData: r.legends || this.state.pageData };
        if (r.wallet && !sameWallet(r.wallet, this.state.wallet)) next.wallet = r.wallet;
        this.setState(next);
      }, '传说完成，成长点已写入星图');
    }

    async deleteLegend(l) {
      if (!confirm('归档该传说任务？')) return;
      await this.safe(async () => { await api.del(`/api/legends/${l.id}`); await this.loadPage('legends'); }, '已归档');
    }

    setRewardTab(tab) { this.rewardTab = tab; this.forceUpdate(); }

    async buyReward(r) {
      await this.safe(async () => {
        const result = await api.post(`/api/rewards/${r.id}/purchase`);
        if (result.wallet) this.setState({ wallet: result.wallet });
        this.rewardTab = 'outbound';
        await this.loadPage('rewards');
      }, '兑换成功，奖励已进入待出库');
    }

    async outboundPurchase(p) {
      if (!confirm('确认这个奖励已经兑现并出库？')) return;
      await this.safe(async () => { await api.post(`/api/rewards/purchases/${p.id}/outbound`); await this.loadPage('rewards'); }, '奖励已出库');
    }

    async deleteReward(r) {
      if (!confirm('删除奖励会写入操作日志，确定删除？')) return;
      await this.safe(async () => { await api.del(`/api/rewards/${r.id}`); await this.loadPage('rewards'); }, '已删除奖励');
    }

    openRewardForm(r = null) {
      this.setState({ modal: {
        title: r ? '编辑奖励' : '新建奖励',
        body: h('form', { id: 'reward-form', className: 'form' },
          h('label', null, '名称', h('input', { name: 'name', defaultValue: r?.name || '', required: true })),
          h('label', null, '内容', h('textarea', { name: 'content', defaultValue: r?.content || '' })),
          h('label', null, '点数类型', h('select', { name: 'point_type', defaultValue: r?.point_type || 'practice' },
            h('option', { value: 'practice', selected: (r?.point_type || 'practice') === 'practice' }, '历练点'),
            h('option', { value: 'growth', selected: r?.point_type === 'growth' }, '成长点')
          )),
          h('label', null, '价格', h('input', { name: 'price', type: 'number', step: '0.5', min: '0.5', defaultValue: r?.price || 1 })),
          h('label', null, '库存', h('input', { name: 'stock', type: 'number', min: '0', defaultValue: r?.stock ?? 1 }))
        ),
        actions: h('button', { onClick: () => this.saveReward(r) }, '保存')
      }});
    }

    async saveReward(r) {
      const data = formData('reward-form');
      data.price = Number(data.price); data.stock = Number(data.stock);
      await this.safe(async () => {
        if (r) await api.put(`/api/rewards/${r.id}`, data);
        else await api.post('/api/rewards', data);
        this.closeModal(); await this.loadPage('rewards');
      }, '奖励已保存');
    }

    async saveState() {
      const f = document.getElementById('state-form');
      this.captureJournalDraft();
      const data = formData(f);
      data.rating = Number(data.rating);
      data.social_feeling = Number(data.social_feeling);
      data.energy = Number(data.energy);
      data.emotions = [...f.querySelectorAll('input[name="emotions"]:checked')].map((x) => x.value);
      await this.safe(async () => {
        const saved = await api.post('/api/states/today', data);
        let nextState = saved.state;
        if (this.journalFiles.length) {
          const uploads = new FormData();
          this.journalFiles.forEach((file) => uploads.append('files', file));
          const uploaded = await api.upload('/api/states/today/images', uploads);
          nextState = uploaded.state || nextState;
        }
        this.clearJournalFiles();
        const current = this.state.pageData || {};
        const recent = (current.recent || []).map((entry) => entry.date === nextState?.date ? { ...entry, ...nextState } : entry);
        this.journalDraft = null;
        this.setState({ pageData: { ...current, state: nextState || current.state, recent } });
      }, '今日日记已保存');
    }

    captureJournalDraft() {
      const form = document.getElementById('state-form');
      if (!form) return this.journalDraft || {};
      const values = formData(form);
      this.journalDraft = {
        journal_title: values.journal_title || '', rating: Number(values.rating || 3),
        emotions: [...form.querySelectorAll('input[name="emotions"]:checked')].map((x) => x.value),
        social_type: values.social_type || '', social_feeling: Number(values.social_feeling || 0),
        energy: Number(values.energy || 0), review_text: values.review_text || ''
      };
      return this.journalDraft;
    }

    updateJournalDraft(key, value) {
      const draft = this.captureJournalDraft();
      this.journalDraft = { ...draft, [key]: value };
    }

    journalField(st, key, fallback = '') {
      if (this.journalDraft && this.journalDraft[key] !== undefined) return this.journalDraft[key];
      return st?.[key] ?? fallback;
    }

    chooseJournalFiles(event) {
      this.captureJournalDraft();
      const selected = [...(event.target.files || [])];
      const existing = this.state.pageData?.state?.images?.length || 0;
      const remain = Math.max(0, 6 - existing - this.journalFiles.length);
      if (selected.length > remain) this.toast(`今天还可以选择 ${remain} 张图片`, 'error');
      const additions = selected.slice(0, remain);
      this.journalFiles = this.journalFiles.concat(additions);
      this.journalPreviewUrls = this.journalFiles.map((file, i) => this.journalPreviewUrls[i] || URL.createObjectURL(file));
      event.target.value = '';
      this.forceUpdate();
    }

    removePendingJournalFile(index) {
      this.captureJournalDraft();
      const url = this.journalPreviewUrls[index];
      if (url) URL.revokeObjectURL(url);
      this.journalFiles.splice(index, 1);
      this.journalPreviewUrls.splice(index, 1);
      this.forceUpdate();
    }

    async reorderJournalImages(index, direction) {
      this.captureJournalDraft();
      const st = this.state.pageData?.state;
      const images = [...(st?.images || [])];
      const target = index + direction;
      if (target < 0 || target >= images.length) return;
      [images[index], images[target]] = [images[target], images[index]];
      await this.safe(async () => {
        const r = await api.post('/api/states/today/images/reorder', { images });
        const current = this.state.pageData || {};
        const nextState = r.state || st;
        this.setState({ pageData: { ...current, state: nextState } });
      }, '封面顺序已更新');
    }

    clearJournalFiles() {
      this.journalPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
      this.journalFiles = []; this.journalPreviewUrls = [];
    }

    async deleteJournalImage(filename) {
      if (!confirm('从今日日记中移除这张照片？')) return;
      this.captureJournalDraft();
      await this.safe(async () => {
        const r = await api.del(`/api/states/today/images/${encodeURIComponent(filename)}`);
        const current = this.state.pageData || {};
        this.setState({ pageData: { ...current, state: r.state || current.state } });
      }, '照片已移除');
    }

    openJournal(entry) {
      const images = entry.image_urls || [];
      this.setState({ modal: {
        title: `${entry.date || ''} · ${entry.journal_title || '未命名的一天'}`,
        body: h('article', { className: 'journal-detail' },
          images.length ? h('div', { className: `journal-detail-gallery count-${Math.min(images.length, 4)}` }, images.map((src, i) => h('img', { key: src, src, alt: `${entry.journal_title || '日记'} ${i + 1}` }))) : h('div', { className: 'journal-detail-empty' }, '这一天没有上传照片'),
          h('div', { className: 'journal-detail-stats' },
            h('span', null, `心情 ${'★'.repeat(clamp(entry.rating || 3, 1, 5))}`),
            h('span', null, `能量 · ${diaryMoodLabel(entry.energy)}`),
            h('span', null, `社交 · ${diaryMoodLabel(entry.social_feeling, 'social')}`)
          ),
          (entry.emotions || []).length ? h('div', { className: 'tagbox journal-tags' }, entry.emotions.map((em) => h('span', { key: em }, em))) : null,
          h('p', { className: 'journal-prose' }, entry.review_text || '没有写下正文。')
        ),
        actions: h('button', { onClick: () => this.closeModal() }, '合上日记')
      }});
    }

    async setVacation() {
      const data = formData('vacation-form');
      await this.safe(async () => { await api.post('/api/vacations/range', data); await this.loadPage('settings'); }, '假期已设置');
    }

    async cancelVacation(v) {
      await this.safe(async () => { await api.post(`/api/vacations/${v.date}/cancel`); await this.loadPage('settings'); }, '假期已取消');
    }

    // Focus timer state machine
    applyFocusToday(data) {
      this.focus.todayStoredSeconds = n(data.today_seconds);
      this.focus.sessions = data.sessions || [];
      this.focus.categories = data.categories || [];
      this.focus.presets = data.presets || [15, 25, 30, 45, 60];
      if (!this.focus.loadedOnce) { this.restoreFocus(); this.focus.loadedOnce = true; }
      this.ensureFocusTicker();
    }

    focusSnapshot() {
      const s = this.focus;
      if (!['running', 'paused', 'finished'].includes(s.mode)) return null;
      return {
        mode: s.mode, plannedSeconds: s.plannedSeconds, remainingSeconds: s.remainingSeconds,
        accumulatedSeconds: this.focusActiveSeconds(), segmentStartedMs: s.mode === 'running' ? s.segmentStartedMs : null,
        startedAt: s.startedAt ? s.startedAt.toISOString() : null, endedAt: s.endedAt ? s.endedAt.toISOString() : null,
        category: s.category, description: s.description,
      };
    }

    persistFocus() {
      const snap = this.focusSnapshot();
      if (!snap) localStorage.removeItem(this.focusStorageKey);
      else localStorage.setItem(this.focusStorageKey, JSON.stringify(snap));
    }

    restoreFocus() {
      try {
        const raw = localStorage.getItem(this.focusStorageKey);
        if (!raw) return;
        const saved = JSON.parse(raw);
        if (!saved || !['running', 'paused', 'finished'].includes(saved.mode)) return;
        const planned = clamp(n(saved.plannedSeconds, 1800) / 60, 1, 240) * 60;
        this.focus.mode = saved.mode;
        this.focus.plannedSeconds = planned;
        this.focus.startedAt = saved.startedAt ? new Date(saved.startedAt) : new Date();
        this.focus.endedAt = saved.endedAt ? new Date(saved.endedAt) : null;
        this.focus.category = saved.category || this.focus.category || '未分类';
        this.focus.description = saved.description || '';
        if (saved.mode === 'running') {
          const segStart = Number(saved.segmentStartedMs || Date.now());
          const before = Number(saved.accumulatedSeconds || 0);
          const active = Math.min(planned, before + Math.max(0, Math.floor((Date.now() - segStart) / 1000)));
          this.focus.accumulatedSeconds = active;
          this.focus.segmentStartedMs = active >= planned ? null : Date.now();
          this.focus.remainingSeconds = Math.max(0, planned - active);
          if (active >= planned) this.finishFocus(true);
        } else if (saved.mode === 'paused') {
          const active = Math.min(planned, Number(saved.accumulatedSeconds || 0));
          this.focus.accumulatedSeconds = active;
          this.focus.remainingSeconds = Math.max(0, planned - active);
          this.focus.segmentStartedMs = null;
        } else if (saved.mode === 'finished') {
          this.focus.accumulatedSeconds = planned;
          this.focus.remainingSeconds = 0;
          this.focus.segmentStartedMs = null;
          this.focus.endedAt = this.focus.endedAt || new Date();
        }
      } catch (err) {
        console.warn('focus timer restore failed', err);
        localStorage.removeItem(this.focusStorageKey);
      }
    }

    focusActiveSeconds() {
      const s = this.focus;
      if (s.mode === 'running' && s.segmentStartedMs) return Math.min(s.plannedSeconds, s.accumulatedSeconds + Math.max(0, Math.floor((Date.now() - s.segmentStartedMs) / 1000)));
      if (s.mode === 'finished') return s.plannedSeconds;
      return Math.min(s.plannedSeconds, n(s.accumulatedSeconds));
    }

    focusDisplaySeconds() { return this.focus.mode === 'idle' ? this.focus.plannedSeconds : this.focus.mode === 'finished' ? 0 : Math.max(0, this.focus.plannedSeconds - this.focusActiveSeconds()); }
    focusTodayPreviewSeconds() { return ['running', 'paused', 'finished'].includes(this.focus.mode) ? this.focus.todayStoredSeconds + this.focusActiveSeconds() : this.focus.todayStoredSeconds; }
    focusStatusText() {
      const mode = this.focus.mode;
      if (mode === 'running') return '专注中 · 当前未保存，完成并结算后计入统计';
      if (mode === 'paused') return '已暂停 · 继续后从当前剩余时间开始';
      if (mode === 'finished') return '完成！请保存本次专注事件';
      return '准备开始 · 取消不计入统计，完成保存后写入专注记录';
    }

    setFocusMinutes(minutes) {
      if (this.focus.mode !== 'idle') return;
      const next = clamp(minutes, 1, 240);
      this.focus.plannedSeconds = next * 60;
      this.focus.remainingSeconds = next * 60;
      this.forceUpdate();
    }

    adjustFocusMinutes(delta) { this.setFocusMinutes(this.focus.plannedSeconds / 60 + Number(delta || 0)); }

    startFocus() {
      const input = document.getElementById('focus-minutes');
      const minutes = clamp(input?.value || this.focus.plannedSeconds / 60, 1, 240);
      Object.assign(this.focus, { mode: 'running', plannedSeconds: minutes * 60, remainingSeconds: minutes * 60, accumulatedSeconds: 0, segmentStartedMs: Date.now(), startedAt: new Date(), endedAt: null, description: '' });
      this.persistFocus();
      this.ensureFocusTicker();
      this.forceUpdate();
    }

    pauseFocus() {
      if (this.focus.mode !== 'running') return;
      this.focus.accumulatedSeconds = this.focusActiveSeconds();
      this.focus.remainingSeconds = Math.max(0, this.focus.plannedSeconds - this.focus.accumulatedSeconds);
      this.focus.segmentStartedMs = null;
      this.focus.mode = 'paused';
      this.persistFocus();
      this.forceUpdate();
    }

    resumeFocus() {
      if (this.focus.mode !== 'paused') return;
      this.focus.mode = 'running';
      this.focus.segmentStartedMs = Date.now();
      this.persistFocus();
      this.ensureFocusTicker();
      this.forceUpdate();
    }

    cancelFocus() {
      if (!confirm('取消后本次专注不会计入统计，确定取消吗？')) return;
      this.resetFocusToIdle(false);
      this.toast('已取消本轮专注，本次不会计入统计。');
    }

    finishFocus(fromRestore = false) {
      this.focus.mode = 'finished';
      this.focus.accumulatedSeconds = this.focus.plannedSeconds;
      this.focus.remainingSeconds = 0;
      this.focus.segmentStartedMs = null;
      this.focus.endedAt = this.focus.endedAt || new Date();
      this.stopFocusTicker();
      this.persistFocus();
      if (!fromRestore) this.toast('本轮专注完成，请保存记录。');
      this.forceUpdate();
    }

    resetFocusToIdle(keepLast = true) {
      const planned = keepLast ? this.focus.plannedSeconds : 30 * 60;
      this.stopFocusTicker();
      Object.assign(this.focus, { mode: 'idle', plannedSeconds: planned, remainingSeconds: planned, accumulatedSeconds: 0, segmentStartedMs: null, startedAt: null, endedAt: null, description: '' });
      localStorage.removeItem(this.focusStorageKey);
      this.forceUpdate();
    }

    discardFocus() {
      if (!confirm('放弃后本次专注不会计入统计，确定放弃记录吗？')) return;
      this.resetFocusToIdle(true);
    }

    async saveFocusSession() {
      if (this.focus.saving) return;
      const category = document.getElementById('focus-settle-category')?.value || this.focus.category || '未分类';
      const description = document.getElementById('focus-description')?.value || this.focus.description || '';
      this.focus.saving = true; this.forceUpdate();
      try {
        const payload = {
          started_at: toLocalString(this.focus.startedAt || new Date()),
          ended_at: toLocalString(this.focus.endedAt || new Date()),
          planned_minutes: Math.round(this.focus.plannedSeconds / 60),
          duration_seconds: this.focus.plannedSeconds,
          category, description,
        };
        const result = await api.post('/api/focus/sessions', payload);
        this.focus.todayStoredSeconds = n(result.today_seconds);
        localStorage.removeItem(this.focusStorageKey);
        this.toast('专注记录已保存。');
        Object.assign(this.focus, { mode: 'idle', remainingSeconds: this.focus.plannedSeconds, accumulatedSeconds: 0, startedAt: null, endedAt: null, description: '' });
        await this.loadPage('focus');
      } catch (err) {
        this.toast(err.message || '保存失败', 'error');
      } finally {
        this.focus.saving = false; this.forceUpdate();
      }
    }

    ensureFocusTicker() {
      if (this.focusTimer || this.focus.mode !== 'running') return;
      this.focusTimer = setInterval(() => {
        const active = this.focusActiveSeconds();
        this.focus.remainingSeconds = Math.max(0, this.focus.plannedSeconds - active);
        if (active >= this.focus.plannedSeconds) { this.finishFocus(); return; }
        this.paintFocusClock();
        if (active % 5 === 0 && active !== this.focusLastPersistSecond) {
          this.focusLastPersistSecond = active;
          this.persistFocus();
        }
      }, 250);
    }

    paintFocusClock(force = false) {
      if (this.state.page !== 'focus') return;
      const display = this.focusDisplaySeconds();
      if (!force && display === this.focusLastPaintSecond) return;
      this.focusLastPaintSecond = display;
      const timer = document.querySelector('[data-focus-clock]');
      const active = document.querySelector('[data-focus-active]');
      const preview = document.querySelector('[data-focus-preview]');
      if (timer) timer.textContent = fmtDuration(display);
      if (active) active.textContent = fmtDuration(this.focusActiveSeconds());
      if (preview) preview.textContent = fmtDuration(this.focusTodayPreviewSeconds());
    }

    stopFocusTicker() { if (this.focusTimer) clearInterval(this.focusTimer); this.focusTimer = null; }

    renderToday(data) {
      data = data || {};
      const quests = data.quests || [];
      const completedCount = quests.filter((q) => isTruthy(q.is_completed)).length;
      const coreRemaining = Math.max(0, 4 - n(data.condition?.total_points));
      return h(F, null,
        h('section', { className: 'today-brand-hero' },
          h('div', { className: 'today-brand-copy' },
            h('p', { className: 'eyebrow' }, 'TO THE STARS · PERSONAL GROWTH SYSTEM'),
            h('h1', null, h('span', null, '把普通的一天，'), h('em', null, '活成有回声的轨迹。')),
            h('p', { className: 'today-brand-lead' }, data.condition?.explain || '今天的每一个小行动，都会成为未来回望时的一颗星。'),
            h('div', { className: 'today-brand-actions' },
              !this.questMultiSelect && h('button', { className: 'brand-primary-action', onClick: () => this.openQuestForm() }, h('span', null, '＋'), '创建今日行动'),
              !this.questMultiSelect && h('button', { className: 'brand-text-action', onClick: () => this.loadPage('states') }, '写今日日记', h('span', null, '↗')),
              h('button', { className: this.questMultiSelect ? 'quest-multi-toggle active' : 'ghost quest-multi-toggle', onClick: () => this.toggleQuestMultiSelect(), disabled: this.batchQuestBusy }, this.questMultiSelect ? '返回' : '多选'),
            ),
            h('div', { className: 'today-brand-metrics' },
              h('div', null, h('span', null, '今日称号'), h('b', null, data.condition?.day_title_preview || '未命名')), 
              h('div', null, h('span', null, '已完成'), h('b', null, `${completedCount} / ${quests.length}`)),
              h('div', null, h('span', null, coreRemaining ? '距离核心' : '核心状态'), h('b', null, coreRemaining ? `${fmtPoints(coreRemaining)} 点` : '已达成'))
            )
          ),
          h(MemoryCarousel, { items: data.memory_items || [], onOpen: (item) => this.openJournal(item), onJournal: () => this.loadPage('states') }),
          h('div', { className: 'today-hero-orbit orbit-one', 'aria-hidden': 'true' }),
          h('div', { className: 'today-hero-orbit orbit-two', 'aria-hidden': 'true' })
        ),
        h('div', { className: 'today-command-strip' },
          h('div', null, h('p', { className: 'eyebrow' }, `TODAY · ${data.date || ''}`), h('b', null, data.is_vacation ? '假期节奏' : '今日行动面板')),
          h('div', { className: 'today-command-actions' },
            h('button', { className: 'brand-text-action', onClick: () => this.openTodayTimeline() }, '今日时间轴', h('span', null, '↗')),
            h('button', { className: 'ghost', onClick: () => this.manualSettlement() }, '普通结算'),
            h('button', { onClick: () => this.endSettlement() }, '日终结算')
          )
        ),
        h(DailyQuestProgress, { data }),
        this.questMultiSelect && h('div', { className: 'quest-multi-hint' }, h('b', null, '编队模式'), h('span', null, '选择多个委托后统一操作；点击“返回”会清空未执行的选择。')),
        h('div', { className: 'grid cols quest-grid' }, quests.length ? quests.map((q, index) => h(QuestCard, { key: q.id, q, index, fresh: q.id === this.recentlyCreatedQuestId, onComplete: (quest, completed) => this.toggleQuest(quest, completed, 'today'), onView: (quest) => this.openQuestDetail(quest, false), multiSelect: this.questMultiSelect, selected: this.selectedQuestIds.has(q.id), onSelect: (id) => this.toggleQuestSelection(id) })) : empty('今天还没有委托。')),
        this.renderQuestBatchBar(quests)
      );
    }

    renderQuests(data) {
      data = data || {};
      const rows = data.quests || [];
      return h(F, null,
        h('div', { className: 'toolbar' },
          h('div', { className: 'row' },
            h('button', { className: this.questMultiSelect ? 'quest-multi-toggle active' : 'ghost quest-multi-toggle', onClick: () => this.toggleQuestMultiSelect(), disabled: this.batchQuestBusy }, this.questMultiSelect ? '返回' : '多选'),
            !this.questMultiSelect && h('button', { onClick: () => this.openQuestForm() }, '新建每日委托'),
            !this.questMultiSelect && h('button', { className: 'ghost', onClick: () => this.loadPage('quests') }, '刷新')
          ),
          h('span', { className: 'muted' }, `当前委托池 ${rows.length} 项`)
        ),
        h(DailyQuestProgress, { data }),
        this.questMultiSelect && h('div', { className: 'quest-multi-hint' }, h('b', null, '编队模式'), h('span', null, '已完成委托也可以选中删除；删除不会影响历练点。')),
        h('div', { className: 'grid cols quest-grid' }, rows.length ? rows.map((q, index) => h(QuestCard, { key: q.id, q, index, fresh: q.id === this.recentlyCreatedQuestId, editable: true, onComplete: (quest, completed) => this.toggleQuest(quest, completed, 'quests'), onView: (quest) => this.openQuestDetail(quest, true), multiSelect: this.questMultiSelect, selected: this.selectedQuestIds.has(q.id), onSelect: (id) => this.toggleQuestSelection(id) })) : empty('暂无委托')),
        this.renderQuestBatchBar(rows)
      );
    }

    renderLegends(rows) {
      rows = rows || [];
      const active = rows.filter((l) => !['completed', '已完成'].includes(l.status)).length;
      return h(F, null,
        h('section', { className: 'workspace-hero legend-workspace-hero' },
          h('div', null, h('p', { className: 'eyebrow' }, 'LONG-TERM CAMPAIGNS · 传说战役'), h('h3', null, '把遥远的目标，拆成一段可以抵达的旅程'), h('p', { className: 'muted' }, '每个检查点都应当明确、可验证，也值得被庆祝。')),
          h('div', { className: 'workspace-metrics' }, h('div', null, h('span', null, '全部战役'), h('b', null, rows.length)), h('div', null, h('span', null, '进行中'), h('b', null, active)), h('button', { onClick: () => this.openLegendForm() }, '＋ 创建传说'))
        ),
        h('div', { className: 'legend-campaign-grid' }, rows.length ? rows.map((l) => h(LegendCard, { key: l.id, l, onCompleteIndicator: (i, completed) => this.completeIndicator(i, completed), onConfirmComplete: (legend) => this.confirmLegendComplete(legend), onAddIndicator: (legend) => this.openIndicatorForm(legend), onEdit: (legend) => this.openLegendForm(legend), onDelete: (legend) => this.deleteLegend(legend) })) : empty('暂无传说任务'))
      );
    }

    renderRewards(data) {
      const rewards = data?.rewards || [];
      const purchases = data?.purchases || [];
      const wallet = data?.wallet || this.state.wallet || {};
      const decoratedRows = rewards.map((r) => ({ ...r, _progressPercent: rewardProgressInfo(r, wallet).percent, _sortGroup: rewardSortGroup(r) }))
        .sort((a, b) => (a._sortGroup - b._sortGroup) || (b._progressPercent - a._progressPercent) || String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN'));
      const sortedPurchases = purchases.slice().sort((a, b) => {
        const ga = a.outbound_status === 'shipped' ? 1 : 0; const gb = b.outbound_status === 'shipped' ? 1 : 0;
        if (ga !== gb) return ga - gb;
        return String(b.purchased_at || '').localeCompare(String(a.purchased_at || ''));
      });
      const pendingCount = purchases.filter((p) => p.outbound_status !== 'shipped').length;
      const shippedCount = purchases.length - pendingCount;
      return h(F, null,
        h('section', { className: 'workspace-hero reward-workspace-hero' },
          h('div', null, h('p', { className: 'eyebrow' }, 'REWARD EXCHANGE · 奖励终端'), h('h3', null, '把积累，兑换成真实生活的回响'), h('p', { className: 'muted' }, '奖励按可兑换状态优先排列；兑换后进入待出库，不会遗漏兑现。')),
          h('div', { className: 'workspace-metrics' },
            h('div', null, h('span', null, '历练点'), h('b', null, fmtPoints(wallet.practice_points))),
            h('div', null, h('span', null, '成长点'), h('b', null, fmtPoints(wallet.growth_points))),
            h('div', null, h('span', null, '待出库'), h('b', null, pendingCount))
          )
        ),
        h('div', { className: 'toolbar reward-toolbar workspace-toolbar' },
          h('div', { className: 'row reward-tabs' },
            h('button', { onClick: () => this.setRewardTab('shop'), className: this.rewardTab === 'shop' ? 'active-tab' : 'ghost' }, '购买界面'),
            h('button', { onClick: () => this.setRewardTab('outbound'), className: this.rewardTab === 'outbound' ? 'active-tab' : 'ghost' }, `出库状态 ${pendingCount ? `· ${pendingCount}` : ''}`)
          ),
          h('button', { className: 'ghost small', onClick: () => this.loadPage('rewards') }, '同步数据')
        ),
        this.rewardTab === 'shop' ? h(F, null,
          h('div', { className: 'section-heading compact-section-heading' }, h('div', null, h('p', { className: 'eyebrow' }, 'AVAILABLE · 可兑换清单'), h('h3', null, `${rewards.length} 份生活奖励`)), h('button', { onClick: () => this.openRewardForm() }, '＋ 新建奖励')),
          h('div', { className: 'grid cols reward-grid' }, decoratedRows.length ? decoratedRows.map((r) => h(RewardCard, { key: r.id, r, wallet, onBuy: (x) => this.buyReward(x), onEdit: (x) => this.openRewardForm(x), onDelete: (x) => this.deleteReward(x) })) : empty('暂无奖励'))
        ) : h(F, null,
          h('div', { className: 'section-heading compact-section-heading' }, h('div', null, h('p', { className: 'eyebrow' }, 'FULFILLMENT · 兑现清单'), h('h3', null, `${pendingCount} 项待兑现 · ${shippedCount} 项已完成`))),
          h('div', { className: 'grid cols reward-grid' }, sortedPurchases.length ? sortedPurchases.map((p) => h(PurchaseCard, { key: p.id, p, onOutbound: (x) => this.outboundPurchase(x) })) : empty('还没有购买记录'))
        )
      );
    }

    renderStates(data) {
      const st = data?.state || {};
      const c = data?.constants || {};
      const recent = data?.recent || [];
      const savedImages = st?.image_urls || [];
      const totalImages = savedImages.length + this.journalPreviewUrls.length;
      return h(F, null,
        h('section', { className: 'panel journal-hero' },
          h('div', null, h('p', { className: 'eyebrow' }, 'DAILY JOURNAL · 每日日记'), h('h3', null, '把今天，留成可以重读的一页'), h('p', { className: 'muted' }, '标题不超过 20 个字。照片、感受与正文一起保存在本机，日终结算仍会按原规则发放记录奖励。')),
          h('div', { className: 'journal-date-stamp' }, h('span', null, 'TODAY'), h('b', null, this.state.boot?.date || ''), h('small', null, '凌晨 4 点切换新的一页'))
        ),
        h('div', { className: 'journal-layout' },
          h('section', { className: 'panel journal-editor' },
            h('div', { className: 'section-heading' }, h('div', null, h('p', { className: 'eyebrow' }, st?.date ? '继续书写' : '新的一页'), h('h3', null, st?.date ? '编辑今日日记' : '写下今日日记')), badge(st?.reward_granted ? '奖励已发放' : '待日终奖励', st?.reward_granted ? '' : 'gold')),
            h('form', { id: 'state-form', className: 'form journal-form' },
              h('label', { className: 'journal-title-field' }, h('span', null, '今天的一句话标题'), h('input', { name: 'journal_title', maxLength: '20', placeholder: '例如：终于越过那座小山', defaultValue: this.journalField(st, 'journal_title', '') === '未命名的一天' ? '' : this.journalField(st, 'journal_title', ''), required: true }), h('small', null, '最多 20 个字，让未来的你一眼记起今天。')),
              h('div', { className: 'journal-rating-row' }, h('span', null, '今天整体怎么样？'), h('div', { className: 'rating-picker' }, [1,2,3,4,5].map((i) => h('label', { key: i }, h('input', { type: 'radio', name: 'rating', value: i, defaultChecked: n(this.journalField(st, 'rating', 3), 3) === i }), h('span', null, `${i}`, h('small', null, '★')))))) ,
              h('div', null, h('p', { className: 'field-title' }, '今天的情绪颜色'), h('div', { className: 'tagbox emotion-tags' }, (c.emotions || []).map((em) => h('label', { key: em }, h('input', { type: 'checkbox', name: 'emotions', value: em, defaultChecked: (this.journalField(st, 'emotions', st?.emotions || []) || []).includes(em) }), h('span', null, em))))),
              h('label', null, '今天与世界的距离', h('select', { name: 'social_type', defaultValue: this.journalField(st, 'social_type', (c.social_types || [])[0] || '') }, (c.social_types || []).map((s) => h('option', { key: s, value: s, selected: this.journalField(st, 'social_type', '') === s }, s)))),
              h('div', { className: 'journal-sliders' },
                h('label', { className: 'journal-range' }, h('span', null, '社交感受', h('small', null, '从想独处到连接充足')), h('input', { type: 'range', name: 'social_feeling', min: '-2', max: '2', step: '1', defaultValue: this.journalField(st, 'social_feeling', 0), onInput: (e) => e.currentTarget.parentNode.querySelector('output').textContent = diaryMoodLabel(e.currentTarget.value, 'social') }), h('output', null, diaryMoodLabel(this.journalField(st, 'social_feeling', 0), 'social'))),
                h('label', { className: 'journal-range energy-range' }, h('span', null, '能量', h('small', null, '从见底到闪耀')), h('input', { type: 'range', name: 'energy', min: '-2', max: '2', step: '1', defaultValue: this.journalField(st, 'energy', 0), onInput: (e) => e.currentTarget.parentNode.querySelector('output').textContent = diaryMoodLabel(e.currentTarget.value) }), h('output', null, diaryMoodLabel(this.journalField(st, 'energy', 0))))
              ),
              h('label', { className: 'journal-body-field' }, h('span', null, '今天发生了什么？'), h('textarea', { name: 'review_text', placeholder: '写下今天最想记住的片段、心情、对话或领悟……', defaultValue: this.journalField(st, 'review_text', '') })),
              h('div', { className: 'journal-photo-field' },
                h('div', { className: 'between' }, h('div', null, h('p', { className: 'field-title' }, '今天的代表照片'), h('small', null, '可选，最多 6 张；第一张会作为日记封面。')), totalImages < 6 && h('label', { className: 'photo-picker photo-add-trigger' }, h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp,image/gif', multiple: true, onChange: (e) => this.chooseJournalFiles(e) }), h('span', null, '＋ 添加照片'))),
                h('div', { className: 'journal-photo-previews' },
                  savedImages.map((src, i) => h('div', { className: `photo-preview saved ${i === 0 ? 'cover-photo' : ''}`, key: src }, h('img', { src, alt: i === 0 ? '日记封面照片' : `已保存照片 ${i + 1}` }), i === 0 && h('span', { className: 'photo-cover-badge' }, '封面'), h('div', { className: 'photo-preview-actions' }, h('button', { type: 'button', className: 'photo-move', disabled: i === 0, onClick: () => this.reorderJournalImages(i, -1), title: '向左移动' }, '←'), h('button', { type: 'button', className: 'photo-move', disabled: i === savedImages.length - 1, onClick: () => this.reorderJournalImages(i, 1), title: '向右移动' }, '→'), h('button', { type: 'button', className: 'photo-remove', onClick: () => this.deleteJournalImage(st.images[i]), title: '移除照片' }, '×')))),
                  this.journalPreviewUrls.map((src, i) => h('div', { className: `photo-preview pending ${savedImages.length === 0 && i === 0 ? 'cover-photo' : ''}`, key: src }, h('img', { src, alt: savedImages.length === 0 && i === 0 ? '待上传日记封面照片' : `待上传照片 ${i + 1}` }), savedImages.length === 0 && i === 0 && h('span', { className: 'photo-cover-badge' }, '封面'), h('div', { className: 'photo-preview-actions' }, h('button', { type: 'button', className: 'photo-move', disabled: i === 0, onClick: () => { if (i > 0) { [this.journalFiles[i - 1], this.journalFiles[i]] = [this.journalFiles[i], this.journalFiles[i - 1]]; [this.journalPreviewUrls[i - 1], this.journalPreviewUrls[i]] = [this.journalPreviewUrls[i], this.journalPreviewUrls[i - 1]]; this.forceUpdate(); } }, title: '向左移动' }, '←'), h('button', { type: 'button', className: 'photo-move', disabled: i === this.journalPreviewUrls.length - 1, onClick: () => { if (i < this.journalFiles.length - 1) { [this.journalFiles[i + 1], this.journalFiles[i]] = [this.journalFiles[i], this.journalFiles[i + 1]]; [this.journalPreviewUrls[i + 1], this.journalPreviewUrls[i]] = [this.journalPreviewUrls[i], this.journalPreviewUrls[i + 1]]; this.forceUpdate(); } }, title: '向右移动' }, '→'), h('button', { type: 'button', className: 'photo-remove', onClick: () => this.removePendingJournalFile(i), title: '移除照片' }, '×')))),
                  totalImages < 6 && h('label', { className: 'photo-preview photo-add-tile', title: '添加照片' }, h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp,image/gif', multiple: true, onChange: (e) => this.chooseJournalFiles(e) }), h('span', null, '+'), h('small', null, '添加')),
                  !savedImages.length && !this.journalPreviewUrls.length ? h('div', { className: 'photo-empty' }, '选几张最能代表今天的照片') : null
                )
              ),
              h('div', { className: 'journal-save-row' }, h('p', { className: 'muted' }, '内容只保存在这台设备。'), h('button', { type: 'button', onClick: () => this.saveState() }, st?.date ? '保存这一页' : '写入今日日记'))
            )
          ),
          h('aside', { className: 'panel journal-prompt' }, h('p', { className: 'eyebrow' }, 'WRITING PROMPTS'), h('h3', null, '如果不知道从哪里写起'), h('ol', null, h('li', null, '今天哪一个瞬间最值得被记住？'), h('li', null, '什么事情消耗了你，又有什么让你恢复？'), h('li', null, '如果给今天一个颜色，它会是什么？')), h('blockquote', null, '日记不需要总结得完美，只需要诚实地留下当时的你。'))
        ),
        h('section', { className: 'journal-archive' },
          h('div', { className: 'journal-archive-head' }, h('div', null, h('p', { className: 'eyebrow' }, 'MEMORY GRID · 回望'), h('h2', null, '过去的每一天')), h('p', null, `${recent.length} 篇日记 · 点击卡片重新走进那一天`)),
          h('div', { className: 'journal-grid' }, recent.length ? recent.map((entry, index) => h(JournalCard, { key: entry.date, entry, index, onOpen: (item) => this.openJournal(item) })) : empty('还没有旧日记。今天写下的第一页，会从这里开始。'))
        )
      );
    }

    renderSettings(data) {
      const boot = data?.boot || this.state.boot || {};
      const vacations = data?.vacations || [];
      const activeVacations = vacations.filter((v) => v.is_active);
      return h(F, null,
        h('section', { className: 'workspace-hero settings-workspace-hero' },
          h('div', null, h('p', { className: 'eyebrow' }, 'RHYTHM & SYSTEM · 节奏设置'), h('h3', null, '系统应该适应生活，而不是逼生活适应系统'), h('p', { className: 'muted' }, '在休息、旅行或高压阶段主动调整节奏，不让连续记录变成新的负担。')),
          h('div', { className: 'workspace-metrics' }, h('div', null, h('span', null, '当前逻辑日'), h('b', null, boot.date || '-')), h('div', null, h('span', null, '有效假期'), h('b', null, activeVacations.length)))
        ),
        h('div', { className: 'settings-layout' },
          h('section', { className: 'settings-primary-card' },
            h('div', { className: 'settings-card-icon', 'aria-hidden': 'true' }, '☾'),
            h('div', { className: 'section-heading' }, h('div', null, h('p', { className: 'eyebrow' }, 'VACATION MODE'), h('h3', null, '安排一段留白'))),
            h('form', { id: 'vacation-form', className: 'form' },
              h('div', { className: 'settings-date-range' },
                h('label', null, '从', h('input', { type: 'date', name: 'start_date', defaultValue: boot.date, required: true })),
                h('span', { 'aria-hidden': 'true' }, '→'),
                h('label', null, '到', h('input', { type: 'date', name: 'end_date', defaultValue: boot.date, required: true }))
              ),
              h('label', null, '为什么需要休息？', h('input', { name: 'reason', placeholder: '旅行、恢复、考试结束后的缓冲……' })),
              h('button', { type: 'button', onClick: () => this.setVacation() }, '启用假期节奏')
            ),
            h('p', { className: 'settings-footnote' }, '假期日不强制四点目标，完成的行动仍然会被记录。')
          ),
          h('aside', { className: 'settings-system-card' },
            h('p', { className: 'eyebrow' }, 'LOCAL FIRST'), h('h3', null, '你的数据留在这台设备'),
            h('div', { className: 'settings-system-row' }, h('span', null, '连接状态'), h('b', null, '● 正常')),
            h('div', { className: 'settings-system-row' }, h('span', null, '日界线'), h('b', null, `凌晨 ${boot.day_boundary_hour ?? 4} 点`)),
            h('div', { className: 'settings-system-row' }, h('span', null, '数据位置'), h('code', { title: boot.data_path || '' }, '本地 SQLite 数据库')),
            h('a', { className: 'settings-doc-link', href: '/docs', target: '_blank' }, '打开 API 文档 ↗')
          )
        ),
        h('section', { className: 'vacation-timeline-section' },
          h('div', { className: 'section-heading' }, h('div', null, h('p', { className: 'eyebrow' }, 'RHYTHM HISTORY'), h('h3', null, '节奏记录'))),
          vacations.length ? h('div', { className: 'vacation-timeline' }, vacations.slice(0, 80).map((v) => h('article', { key: v.date, className: `vacation-timeline-item ${v.is_active ? 'active' : 'inactive'}` },
            h('time', null, v.date), h('div', null, h('b', null, v.reason || '给自己留白'), h('span', null, v.is_active ? '假期节奏生效中' : '已恢复普通节奏')), v.is_active && h('button', { className: 'small ghost', onClick: () => this.cancelVacation(v) }, '恢复普通日')
          ))) : empty('还没有设置过假期。')
        )
      );
    }

    renderStats(data) {
      data = data || {};
      const focus = data.focus || {};
      const daily = focus.daily || [];
      const sumSeconds = daily.reduce((acc, d) => acc + n(d.seconds), 0);
      const avg = daily.length ? Math.round(sumSeconds / daily.length) : 0;
      const sessions = (focus.sessions || []).slice(0, 80).map((s) => ({ started_at: s.started_at || '', business_date: s.business_date || '', duration_label: s.duration_label || fmtDuration(s.duration_seconds), category: s.category || '未分类', description: s.description || '' }));
      return h(F, null,
        h('section', { className: 'analytics-hero' },
          h('div', { className: 'analytics-hero-copy' }, h('p', { className: 'eyebrow' }, 'GROWTH REVIEW · 成长复盘'), h('h2', null, '看见趋势，而不是被数字审判'), h('p', null, '统计用于发现节奏、理解选择，并帮助下一次行动更轻松。')),
          h('div', { className: 'analytics-score' }, h('span', null, '普通日达成率'), h('b', null, `${fmtPoints(data.sum?.completion_rate)}%`), h('small', null, `${data.sum?.completion_done_days || 0} / ${data.sum?.completion_total_days || 0} 天`))
        ),
        h('div', { className: 'analytics-metric-row' },
          h('article', null, h('span', null, '今日专注'), h('b', null, fmtDuration(focus.today_seconds)), h('small', null, '已保存记录')),
          h('article', null, h('span', null, '历史专注'), h('b', null, fmtDuration(focus.total_seconds)), h('small', null, '全部专注事件')),
          h('article', null, h('span', null, '行动资产'), h('b', null, `${data.sum?.active_quests || 0} / ${data.sum?.legend_count || 0}`), h('small', null, '每日委托 / 传说任务')),
          h('article', null, h('span', null, '历练点池'), h('b', null, fmtPoints((data.sum?.wallet || this.state.wallet)?.practice_points)), h('small', null, '可兑换资源'))
        ),
        h('section', { className: 'analytics-focus-panel' },
          h('div', { className: 'between' }, h('div', null, h('h3', null, '专注统计'), h('p', { className: 'muted' }, '来自番茄钟保存后的专注事件；取消或未保存的计时不纳入统计。')), badge(`近 ${daily.length || 14} 日`, 'gold')),
          h('div', { className: 'grid cols focus-stat-grid' },
            h('div', { className: 'focus-stat' }, h('span', null, '今日专注'), h('b', null, fmtDuration(focus.today_seconds))),
            h('div', { className: 'focus-stat' }, h('span', null, '历史总专注'), h('b', null, fmtDuration(focus.total_seconds))),
            h('div', { className: 'focus-stat' }, h('span', null, '最近日均'), h('b', null, fmtDuration(avg)))
          ),
          h(FocusChart, { daily })
        ),
        h('div', { className: 'analytics-disclosures' },
        h(DataDisclosure, { eyebrow: 'FOCUS LOG', title: '专注事件记录', summary: `${sessions.length} 条近期记录`, open: true }, h(Table, { rows: sessions, columns: [
          { key: 'started_at', label: '发生时间' }, { key: 'business_date', label: '业务日' }, { key: 'duration_label', label: '时长' }, { key: 'category', label: '分类' }, { key: 'description', label: '描述' }
        ] })),
        h(DataDisclosure, { eyebrow: 'SETTLEMENTS', title: '最近结算', summary: `${(data.sett || []).length} 条` }, h(Table, { rows: (data.sett || []).slice(0, 20), columns: [
          { key: 'date', label: '日期' }, { key: 'day_title', label: '称号' }, { key: 'total_points', label: '完成点数' }, { key: 'points_banked', label: '入池' }, { key: 'state_bonus', label: '状态奖励' }
        ] })),
        h(DataDisclosure, { eyebrow: 'POINT LEDGER', title: '点数流水', summary: `${(data.tx || []).length} 条` }, h(Table, { rows: (data.tx || []).slice(0, 50), columns: [
          { key: 'created_at', label: '时间' }, { key: 'point_type', label: '类型' }, { key: 'amount', label: '变化' }, { key: 'reason', label: '原因' }, { key: 'balance_after', label: '余额' }
        ] })),
        h(DataDisclosure, { eyebrow: 'JOURNAL INDEX', title: '日记摘要', summary: `${(data.st || []).length} 篇` }, h(Table, { rows: (data.st || []).slice(0, 20), columns: [
            { key: 'date', label: '日期' }, { key: 'journal_title', label: '标题' }, { key: 'rating', label: '评价' }, { key: 'energy', label: '能量' }, { key: 'review_text', label: '正文' }
          ] })),
        h(DataDisclosure, { eyebrow: 'CATEGORY MAP', title: '分类统计', summary: `${(data.cat || []).length} 个分类` }, h(Table, { rows: data.cat || [], columns: [
            { key: 'category', label: '分类' }, { key: 'count', label: '数量' }, { key: 'points', label: '点数' }
          ] })),
        h(DataDisclosure, { eyebrow: 'CAMPAIGN STATUS', title: '传说进度', summary: `${(data.leg || []).length} 项长期目标` }, h(Table, { rows: data.leg || [], columns: [
          { key: 'title', label: '任务' }, { key: 'status', label: '状态' }, { key: 'deadline', label: '截止' }, { key: 'done', label: '完成指标' }, { key: 'total', label: '总指标' }
        ] }))
        )
      );
    }

    renderFocusActions() {
      const mode = this.focus.mode;
      if (mode === 'running') return [h('button', { key: 'pause', className: 'ghost', onClick: () => this.pauseFocus() }, '暂停'), h('button', { key: 'cancel', className: 'danger', onClick: () => this.cancelFocus() }, '取消')];
      if (mode === 'paused') return [h('button', { key: 'resume', onClick: () => this.resumeFocus() }, '继续'), h('button', { key: 'cancel', className: 'danger', onClick: () => this.cancelFocus() }, '取消')];
      if (mode === 'finished') return [h('button', { key: 'save', onClick: () => this.saveFocusSession(), disabled: this.focus.saving }, '保存记录'), h('button', { key: 'discard', className: 'ghost', onClick: () => this.discardFocus() }, '放弃记录')];
      return h('button', { onClick: () => this.startFocus() }, '开始专注');
    }

    renderFocusSettlement() {
      if (this.focus.mode !== 'finished') return null;
      const cats = this.focus.categories?.length ? this.focus.categories : ['实践', '知识', '学习', '工作', '其他', '未分类'];
      return h('section', { className: 'panel focus-finish-panel' },
        h('div', { className: 'focus-finish-title' }, '完成！'),
        h('div', { className: 'grid cols focus-mini-stats' },
          h('div', null, h('span', null, '本次专注'), h('b', null, fmtDuration(this.focus.plannedSeconds))),
          h('div', null, h('span', null, '保存后今日专注'), h('b', null, fmtDuration(this.focus.todayStoredSeconds + this.focus.plannedSeconds))),
          h('div', null, h('span', null, '开始 / 结束'), h('b', null, `${toLocalString(this.focus.startedAt)} → ${toLocalString(this.focus.endedAt)}`))
        ),
        h('div', { className: 'form focus-settle-form' },
          h('label', null, '专注分类', h('select', { id: 'focus-settle-category', defaultValue: this.focus.category, onChange: (e) => { this.focus.category = e.target.value || '未分类'; this.persistFocus(); } }, cats.map((c) => h('option', { key: c, value: c, selected: c === this.focus.category }, c)))),
          h('label', null, '专注事件描述', h('textarea', { id: 'focus-description', placeholder: '这轮专注做了什么？例如：完成英语阅读第 3 篇。', defaultValue: this.focus.description || '', onInput: (e) => { this.focus.description = e.target.value; this.persistFocus(); } })),
          h('div', { className: 'row' }, h('button', { onClick: () => this.saveFocusSession(), disabled: this.focus.saving }, '保存专注事件'), h('button', { className: 'ghost', onClick: () => this.discardFocus() }, '放弃记录'))
        )
      );
    }

    renderFocus() {
      const s = this.focus;
      const minutes = Math.round(s.plannedSeconds / 60);
      const disabled = s.mode !== 'idle';
      const cats = s.categories?.length ? s.categories : ['实践', '知识', '学习', '工作', '其他', '未分类'];
      return h(F, null,
        h('div', { className: 'focus-hero panel' },
          h('div', null, h('p', { className: 'eyebrow' }, 'FOCUS TIMER · 番茄钟'), h('h3', null, '把一次行动，落成一条专注记录'), h('p', { className: 'muted' }, '完成后进入结算页；保存后才计入统计。暂停不会计时，取消不会入库。')),
          h('div', { className: 'focus-today-card' }, h('span', null, '今日专注'), h('b', { 'data-focus-preview': '1' }, fmtDuration(this.focusTodayPreviewSeconds())), h('small', null, '逻辑日统计，凌晨 4 点切换'))
        ),
        h('div', { className: 'focus-layout' },
          h('section', { className: `panel focus-clock-panel ${s.mode}` },
            h('div', { className: 'focus-status' }, this.focusStatusText()),
            h('div', { className: 'focus-timer', 'data-focus-clock': '1' }, fmtDuration(this.focusDisplaySeconds())),
            h('div', { className: 'focus-orbit' }),
            h('div', { className: 'grid cols focus-mini-stats' },
              h('div', null, h('span', null, '本轮计划'), h('b', null, fmtDuration(s.plannedSeconds))),
              h('div', null, h('span', null, '当前已专注'), h('b', { 'data-focus-active': '1' }, fmtDuration(this.focusActiveSeconds()))),
              h('div', null, h('span', null, '已保存今日'), h('b', null, fmtDuration(s.todayStoredSeconds)))
            ),
            h('div', { className: 'focus-actions' }, this.renderFocusActions())
          ),
          h('aside', { className: 'panel focus-control-panel' },
            h('h3', null, '倒计时设置'),
            h('div', { className: 'focus-stepper' },
              h('button', { className: 'ghost', onClick: () => this.adjustFocusMinutes(-5), disabled }, '-5'),
              h('label', null, '分钟', h('input', { id: 'focus-minutes', type: 'number', min: '1', max: '240', value: minutes, disabled, onChange: (e) => this.setFocusMinutes(e.target.value) })),
              h('button', { className: 'ghost', onClick: () => this.adjustFocusMinutes(5), disabled }, '+5')
            ),
            h('div', { className: 'focus-presets' }, s.presets.map((p) => h('button', { key: p, className: `ghost ${p === minutes ? 'active' : ''}`, onClick: () => this.setFocusMinutes(p), disabled }, `${p} 分钟`))),
            h('label', { className: 'focus-category-label' }, '默认分类', h('select', { value: s.category, disabled: s.mode === 'running' || s.mode === 'paused', onChange: (e) => { this.focus.category = e.target.value || '未分类'; this.persistFocus(); this.forceUpdate(); } }, cats.map((c) => h('option', { key: c, value: c, selected: c === s.category }, c)))),
            h('div', { className: 'focus-help' }, h('b', null, '规则'), h('p', null, '开始后可以暂停或取消；倒计时自然结束后进入“完成”结算区，填写分类和描述后保存。'), h('p', null, '只有保存后的专注事件会进入“统计复盘”的每日时长、总时长和事件记录。'))
          )
        ),
        this.renderFocusSettlement(),
        h('section', { className: 'panel' },
          h('div', { className: 'between' }, h('h3', null, '今日专注事件'), badge(`${s.sessions.length} 条`)),
          h('div', { className: 'focus-session-list' }, s.sessions?.length ? s.sessions.map((fs) => h('article', { key: fs.id, className: 'focus-session-card' },
            h('div', null, h('b', null, fs.category || '未分类'), h('span', { className: 'muted' }, ` ${fs.started_at || ''}`), fs.description ? h('p', null, fs.description) : h('p', { className: 'muted' }, '没有描述')),
            h('strong', null, fs.duration_label || fmtDuration(fs.duration_seconds))
          )) : empty('今天还没有保存专注记录。完成一轮番茄钟后会出现在这里。'))
        )
      );
    }

    // ---------- 日程表 / 时间轴 ----------

    scheduleDay() { return this.state.pageData?.day || null; }

    scheduleMinuteToTime(offset) {
      const total = ((Math.round(n(offset)) % 1440) + 1440) % 1440;
      const clock = (total + 240) % 1440;
      return `${String(Math.floor(clock / 60)).padStart(2, '0')}:${String(clock % 60).padStart(2, '0')}`;
    }

    scheduleDefaultRange(day) {
      let startMinute = 300;
      if (day?.is_today) {
        const now = new Date();
        const offset = ((now.getHours() * 60 + now.getMinutes()) - 240 + 1440) % 1440;
        startMinute = Math.min(1380, Math.ceil((offset + 10) / 30) * 30);
      }
      return [this.scheduleMinuteToTime(startMinute), this.scheduleMinuteToTime(Math.min(1440, startMinute + 120))];
    }

    scheduleRangeHint(day) {
      const startHour = day?.timeline?.start_hour ?? 4;
      return `时间轴范围 ${startHour}:00 → 次日 ${startHour}:00，可精确到分钟；结束时间填 ${String(startHour).padStart(2, '0')}:00 表示到次日同一时刻结束。`;
    }

    async changeScheduleWeek(date) {
      this.scheduleWeekDate = date;
      this.scheduleView = 'week';
      await this.loadPage('schedule');
    }

    async openScheduleDay(date) {
      await this.loadScheduleDay(date);
    }

    async changeScheduleDay(date) { await this.loadScheduleDay(date); }

    async openTodayTimeline() {
      this.scheduleView = 'day';
      this.scheduleDate = this.state.boot?.date || todayIso();
      await this.loadPage('schedule');
    }

    async loadScheduleDay(date) {
      const target = date || this.scheduleDate || this.state.boot?.date || todayIso();
      if (this.state.page !== 'schedule') {
        this.scheduleView = 'day';
        this.scheduleDate = target;
        await this.loadPage('schedule');
        return;
      }
      try {
        const day = await api.get(`/api/schedule/day?date=${target}`);
        const current = this.state.pageData || {};
        this.scheduleView = 'day';
        this.scheduleDate = day.date;
        this.questMultiSelect = false;
        this.selectedQuestIds = new Set();
        this.setState({ pageData: { ...current, day } });
      } catch (err) {
        this.toast(err.message || '日程加载失败', 'error');
      }
    }

    openScheduleQuestPlanForm(day, questId = '') {
      const quests = day?.quests || [];
      const [start, end] = this.scheduleDefaultRange(day);
      const selected = questId === '' || questId === null || questId === undefined ? '' : String(questId);
      this.setState({ modal: {
        title: '把每日委托放进时间轴',
        body: h('form', {
          id: 'schedule-quest-form',
          className: 'form sch-detail',
          onSubmit: (event) => {
            event.preventDefault();
            this.submitSchedulePlan({ formId: 'schedule-quest-form', kind: 'quest', date: day?.date });
          },
        },
          h('label', null, '选择委托', h('select', { name: 'quest_id', defaultValue: selected },
            h('option', { value: '' }, quests.length ? '请选择一项委托…' : '当天还没有每日委托'),
            quests.map((q) => h('option', { key: q.id, value: String(q.id), selected: String(q.id) === selected },
              `${q.title} · ${q.difficulty}（${fmtPoints(q.points)} 点）${q.scheduled ? ` · 已排期 ${q.plan_time_label}` : ''}`)))),
          h('div', { className: 'sch-time-fields' },
            h('label', null, '开始时间', h('input', { type: 'time', name: 'start', defaultValue: start, required: true })),
            h('label', null, '结束时间', h('input', { type: 'time', name: 'end', defaultValue: end, required: true }))),
          h('p', { className: 'sch-form-hint' }, this.scheduleRangeHint(day)),
          h('p', { className: 'sch-form-hint' }, h('b', null, '绑定说明：'), '委托计划与每日委托严格绑定，之后修改标题或内容会同步写入委托本身；修改时间只影响时间轴上的安排。'),
          !quests.length && h('p', { className: 'sch-form-hint' }, '可以先到「每日委托」页新建委托，再回来排期。')
        ),
        actions: h(F, null,
          h('button', { className: 'ghost', onClick: () => this.closeModal() }, '取消'),
          h('button', { type: 'submit', form: 'schedule-quest-form', disabled: !quests.length }, '添加到时间轴'))
      } });
    }

    openScheduleFreePlanForm(day) {
      const [start, end] = this.scheduleDefaultRange(day);
      this.setState({ modal: {
        title: '添加自定义计划',
        body: h('form', {
          id: 'schedule-free-form',
          className: 'form sch-detail',
          onSubmit: (event) => {
            event.preventDefault();
            this.submitSchedulePlan({ formId: 'schedule-free-form', kind: 'free', date: day?.date });
          },
        },
          h('label', null, '计划标题', h('input', { name: 'title', placeholder: '例如：跑步 + 拉伸', required: true })),
          h('label', null, '计划内容', h('textarea', { name: 'content', placeholder: '这段时间具体想做什么？' })),
          h('div', { className: 'sch-time-fields' },
            h('label', null, '开始时间', h('input', { type: 'time', name: 'start', defaultValue: start, required: true })),
            h('label', null, '结束时间', h('input', { type: 'time', name: 'end', defaultValue: end, required: true }))),
          h('p', { className: 'sch-form-hint' }, this.scheduleRangeHint(day)),
          h('p', { className: 'sch-form-hint' }, h('b', null, '独立计划：'), '不与任何委托绑定，编辑标题、内容与时间都不会影响每日委托。')
        ),
        actions: h(F, null,
          h('button', { className: 'ghost', onClick: () => this.closeModal() }, '取消'),
          h('button', { type: 'submit', form: 'schedule-free-form' }, '添加到时间轴'))
      } });
    }

    async submitSchedulePlan({ formId, kind, planId = null, date }) {
      const form = document.getElementById(formId);
      if (!form) return;
      const data = formData(form);
      const payload = { plan_date: date, start: data.start, end: data.end };
      if (kind === 'quest' && !planId) {
        const questId = Number(data.quest_id || 0);
        if (!questId) { this.toast('请先选择一项每日委托', 'error'); return; }
        payload.quest_id = questId;
      } else {
        payload.title = (data.title || '').trim();
        payload.content = data.content || '';
        if (!payload.title) { this.toast('请填写计划标题', 'error'); return; }
      }
      await this.safe(async () => {
        if (planId) await api.put(`/api/schedule/plans/${planId}`, payload);
        else await api.post('/api/schedule/plans', payload);
        this.closeModal();
        await this.loadScheduleDay(date);
      }, planId ? '计划已更新' : '计划已加入时间轴');
    }

    openSchedulePlanDetail(plan) {
      const day = this.scheduleDay();
      const quest = plan.kind === 'quest' ? (day?.quests || []).find((q) => q.id === plan.quest_id) : null;
      const canReopen = plan.kind === 'quest' && plan.completed && n(plan.banked_points) <= 0;
      const kindBadge = plan.kind === 'quest'
        ? badge(plan.completed ? '委托计划 · 已完成' : '委托计划 · 未完成', plan.completed ? 'ok' : 'pending')
        : badge('自定义计划', 'info');
      this.setState({ modal: {
        title: plan.kind === 'quest' ? '委托计划详情' : '自定义计划详情',
        body: h('form', {
          id: 'schedule-plan-form',
          className: 'form sch-detail',
          onSubmit: (event) => {
            event.preventDefault();
            this.submitSchedulePlan({ formId: 'schedule-plan-form', kind: plan.kind, planId: plan.id, date: plan.plan_date });
          },
        },
          h('div', { className: `sch-detail-hero color-${plan.color_key}` },
            h('div', null,
              h('b', null, plan.title),
              h('div', { className: 'row', style: { marginTop: '6px' } },
                badge(`${plan.start_label} → ${plan.end_label}`, 'gold'),
                badge(`时长 ${plan.duration_label}`),
                kindBadge,
                quest && badge(`${quest.difficulty} · ${fmtPoints(quest.points)} 点`),
                quest && quest.category && badge(quest.category),
                quest && quest.is_required && badge('必要委托'))),
            h('span', null, plan.plan_date)),
          h('label', null, '计划标题', h('input', { name: 'title', defaultValue: plan.title, required: true })),
          h('label', null, '计划内容', h('textarea', { name: 'content', defaultValue: plan.content || '', placeholder: '这一段时间具体想做什么？' })),
          h('div', { className: 'sch-time-fields' },
            h('label', null, '开始时间', h('input', { type: 'time', name: 'start', defaultValue: plan.start_label, required: true })),
            h('label', null, '结束时间', h('input', { type: 'time', name: 'end', defaultValue: plan.end_label, required: true }))),
          h('p', { className: 'sch-form-hint' }, plan.kind === 'quest'
            ? '该计划与每日委托严格绑定：修改标题或内容会同步更新每日委托本身，修改时间只影响时间轴安排。'
            : '自定义计划独立存在，标题、内容与时间都可以自由修改。'),
          h('p', { className: 'sch-form-hint' }, this.scheduleRangeHint(day)),
        ),
        actions: h(F, null,
          h('button', { className: 'danger', onClick: () => this.deleteSchedulePlan(plan) }, '删除计划'),
          h('span', { className: 'modal-actions-spacer' }),
          canReopen && h('button', { className: 'ghost', onClick: () => this.toggleScheduleQuest(plan, false) }, '取消完成'),
          plan.kind === 'quest' && !plan.completed && h('button', { className: 'ghost', onClick: () => this.toggleScheduleQuest(plan, true) }, '标记委托完成'),
          h('button', { className: 'ghost', onClick: () => this.closeModal() }, '取消'),
          h('button', { type: 'submit', form: 'schedule-plan-form' }, '保存修改'))
      } });
    }

    async deleteSchedulePlan(plan) {
      const extra = plan.kind === 'quest' ? '（只删除时间轴上的安排，不会删除每日委托）' : '';
      if (!confirm(`删除计划「${plan.title}」？${extra}`)) return;
      await this.safe(async () => {
        await api.del(`/api/schedule/plans/${plan.id}`);
        this.closeModal();
        await this.loadScheduleDay(plan.plan_date);
      }, '计划已删除');
    }

    async toggleScheduleQuest(plan, completed) {
      await this.safe(async () => {
        await api.post(`/api/quests/${plan.quest_id}/complete`, { completed });
        this.closeModal();
        await this.loadScheduleDay(plan.plan_date);
      }, completed ? '委托已完成，卡片已点亮' : '委托已重新开启');
    }

    setScheduleZoom(value) {
      this.scheduleZoom = n(value, 1);
      this.setState({});
      setTimeout(() => this.scrollScheduleTimeline(), 0);
    }

    /* 放大后把「现在」或第一段安排滚到视野中央，避免一放大就找不到重点。 */
    scrollScheduleTimeline() {
      const box = document.querySelector('.sch-tl-scroll');
      if (!box || box.scrollWidth <= box.clientWidth + 4) return;
      const anchor = box.querySelector('.sch-now') || box.querySelector('.sch-clip');
      if (!anchor) return;
      const left = anchor.offsetLeft - (box.clientWidth - anchor.offsetWidth) / 2;
      box.scrollLeft = Math.max(0, left);
    }

    renderScheduleLegend(legend = []) {
      const items = legend.length ? legend : [
        { key: 'quest', label: '每日委托 · 未完成' },
        { key: 'quest-done', label: '每日委托 · 已完成' },
        { key: 'free', label: '自定义计划' },
      ];
      return h('div', { className: 'sch-legend' },
        items.map((item) => h('span', { key: item.key, className: `sch-legend-item color-${item.key}` },
          h('i', { 'aria-hidden': 'true' }), item.label)));
    }

    renderScheduleWeek(week) {
      const days = week.days || [];
      const buckets = week.buckets || [];
      const totalPlans = days.reduce((acc, d) => acc + n(d.plan_count), 0);
      const totalPending = days.reduce((acc, d) => acc + n(d.unscheduled_count), 0);
      return h('section', { className: 'panel sch-board-panel' },
        h('div', { className: 'sec-head' },
          h('div', null,
            h('p', { className: 'eyebrow' }, 'WEEK BOARD · 一周节奏'),
            h('h3', null, week.week_label || ''),
            h('p', null, `每格 4 小时，一眼看清一周的大致排布。本周共 ${totalPlans} 项安排${totalPending ? `，${totalPending} 项还没排期` : ''}；点击日期进入当天时间轴。`)),
          this.renderScheduleLegend(week.color_legend || [])),
        h('div', { className: 'sch-board-scroll' },
          h('table', { className: 'sch-board' },
            h('thead', null, h('tr', null,
              h('th', { className: 'sch-col-time' }, h('div', { className: 'sch-timecell' }, h('b', null, '时段'))),
              days.map((d) => h('th', { key: d.date },
                h('button', {
                  className: `sch-dayhead ${d.is_today ? 'is-today' : ''} ${d.is_vacation ? 'is-vacation' : ''}`,
                  title: `查看 ${d.date} 的时间轴`,
                  onClick: () => this.openScheduleDay(d.date),
                },
                  h('span', { className: 'sch-dayhead-weekday' }, d.weekday_label),
                  h('b', { className: 'sch-dayhead-date' }, `${d.month}/${d.day_number}`),
                  h('small', { className: 'sch-dayhead-meta' }, d.is_today ? '今天' : d.is_vacation ? '假期' : `${n(d.plan_count)} 项安排`),
                  n(d.unscheduled_count) > 0 && h('small', { className: 'sch-dayhead-meta' }, `待排期 ${n(d.unscheduled_count)}`)))))),
            h('tbody', null, buckets.map((bucket) => h('tr', { key: bucket.key },
              h('th', { className: 'sch-col-time' }, h('div', { className: 'sch-timecell' }, h('b', null, bucket.name), h('span', null, bucket.range_label))),
              days.map((d) => {
                const cell = (d.buckets || []).find((b) => b.key === bucket.key) || { plans: [] };
                return h('td', { key: d.date },
                  h('div', { className: `sch-cell ${d.is_today ? 'is-today' : ''}` },
                    cell.plans.length
                      ? cell.plans.map((p) => h('button', {
                          key: p.id,
                          className: `sch-entry color-${p.color_key} ${p.completed ? 'is-done' : ''}`,
                          title: `${p.time_label} · ${p.title}`,
                          onClick: () => this.openScheduleDay(d.date),
                        }, h('b', null, p.title), h('span', null, p.start_label)))
                      : h('span', { className: 'sch-cell-empty' }, '—')));
              }))))) ),
        h('div', { className: 'sch-tl-foot' },
          h('span', null, '时间重叠的安排会自动分行；点击任意片段可查看详情并随时编辑。'),
          h('button', { className: 'ghost small', onClick: () => this.openTodayTimeline() }, '打开今日时间轴 →')));
    }

    renderScheduleDay(day) {
      const plans = day.plans || [];
      const quests = day.quests || [];
      const unscheduled = day.unscheduled_quests || [];
      const ticks = day.timeline?.ticks || [];
      const laneCount = Math.max(1, n(day.lane_count, 1));
      const zoom = n(this.scheduleZoom, 1);
      const zoomSteps = [['全览', 1], ['放大', 1.7], ['精细', 2.6]].map(([label, value]) => ({ label, value }));
      const percent = (minute) => `${(n(minute) / 1440) * 100}%`;
      const hourLines = [];
      for (let minute = 0; minute <= 1440; minute += 60) hourLines.push(minute);
      let nowOffset = null;
      if (day.is_today) {
        const now = new Date();
        nowOffset = ((now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60) - 240 + 1440) % 1440;
      }

      const ruler = h('div', { key: 'ruler', className: 'sch-ruler', 'aria-hidden': 'true' },
        ticks.map((t) => h('span', {
          key: t.minute,
          className: `sch-ruler-tick ${t.is_major ? 'major' : ''}`,
          style: { left: percent(t.minute) },
        }, t.is_major ? h('em', null, t.label) : null)));

      const gridlines = h('div', { key: 'grid', className: 'sch-lanes-bg', 'aria-hidden': 'true' },
        [1, 3, 5].map((index) => h('span', {
          key: `band${index}`,
          className: 'sch-band',
          style: { left: percent(index * 240), width: percent(240) },
        })).concat(hourLines.map((minute) => h('span', {
          key: minute,
          className: `sch-gridline ${minute % 240 === 0 ? 'major' : ''}`,
          style: { left: percent(minute) },
        }))));

      const nowMarker = nowOffset === null ? null : h('span', {
        key: 'now',
        className: 'sch-now',
        style: { left: percent(nowOffset) },
      }, h('b', null, `现在 ${this.scheduleMinuteToTime(nowOffset)}`));

      const lanes = Array.from({ length: laneCount }, (_, index) => laneCount - 1 - index).map((lane) => {
        const clips = plans.filter((p) => n(p.lane) === lane).map((p) => {
          const width = n(p.end_minute) - n(p.start_minute);
          const marks = [p.completed ? 'is-done' : '', width < 150 ? 'is-narrow' : '', width < 62 ? 'is-tiny' : ''].filter(Boolean).join(' ');
          const timeText = width < 62 ? '' : (width >= 150 ? p.time_label : p.start_label);
          return h('button', {
            key: p.id,
            className: `sch-clip color-${p.color_key} ${marks}`,
            style: { left: percent(p.start_minute), width: percent(width) },
            title: `${p.time_label} · ${p.title} · 点击查看详情`,
            onClick: () => this.openSchedulePlanDetail(p),
          }, h('b', null, p.title), timeText ? h('span', null, timeText) : null);
        });
        return h('div', { key: lane, className: 'sch-lane' }, clips);
      });

      const body = plans.length
        ? h('div', { key: 'lanes', className: 'sch-lanes' }, [gridlines, nowMarker, ...lanes])
        : h('div', { key: 'empty', className: 'sch-tl-empty' },
            h('b', null, '这一天还是空的'),
            h('span', null, '点「＋ 添加委托计划」把每日委托放进时间轴，或用「＋ 自定义计划」直接安排一段自己的时间。'));

      const foot = h('div', { key: 'foot', className: 'sch-tl-foot' },
        h('span', null, nowOffset === null
          ? '时间轴以凌晨 04:00 作为一天的起点。'
          : `红粉色竖线是现在的位置（${this.scheduleMinuteToTime(nowOffset)}）。`),
        h('span', null, '两端对齐 04:00 → 次日 04:00；时间重叠的安排自动分行。'));

      const timelinePanel = h('section', { className: 'panel sch-day-panel' },
        h('div', { className: 'sec-head' },
          h('div', null,
            h('p', { className: 'eyebrow' }, `DAY TIMELINE · ${day.date}`),
            h('h3', null, `${day.weekday_label} ${day.month}/${day.day_number}${day.relative_label ? ` · ${day.relative_label}` : ''}`),
            h('p', null, `04:00 → 次日 04:00 共 24 小时，可精确到分钟；已安排 ${plans.length} 项，占用 ${day.total_label || '0 分钟'}${unscheduled.length ? `，还有 ${unscheduled.length} 项待排期` : ''}。`)),
          this.renderScheduleLegend(day.color_legend || [])),
        h('div', { className: 'sch-day-actions' },
          h('div', { className: 'row' },
            h('button', { onClick: () => this.openScheduleQuestPlanForm(day) }, '＋ 添加委托计划'),
            h('button', { className: 'ghost', onClick: () => this.openScheduleFreePlanForm(day) }, '＋ 自定义计划')),
          h('div', { className: 'row' },
            h('span', { className: 'muted sch-zoom-label' }, '时间轴'),
            h('div', { className: 'sch-zoom' }, zoomSteps.map((step) => h('button', {
              key: step.label,
              className: zoom === step.value ? 'is-on' : '',
              onClick: () => this.setScheduleZoom(step.value),
            }, step.label))))),
        h('div', { className: 'sch-tl', style: { '--tl-zoom': String(zoom) } },
          h('div', { className: 'sch-tl-scroll' },
            h('div', { className: 'sch-tl-track' }, [ruler, body, foot]))));

      const poolList = h('div', { className: 'sch-pool' }, unscheduled.map((q) => h('button', {
        key: q.id,
        className: 'sch-pool-item color-quest',
        title: `把「${q.title}」放进时间轴`,
        onClick: () => this.openScheduleQuestPlanForm(day, q.id),
      },
        h('span', { className: 'sch-pool-main' },
          h('b', null, q.title),
          h('span', null, `${q.category || '未分类'} · ${q.difficulty} 级 · ${fmtPoints(q.points)} 点`)),
        h('span', { className: 'sch-pool-add' }, '排期 →'))));

      const poolPanel = h('section', { className: 'panel sch-pool-panel' },
        h('div', { className: 'sec-head' },
          h('div', null,
            h('p', { className: 'eyebrow' }, 'QUEST POOL · 当日委托'),
            h('h3', null, unscheduled.length ? `还有 ${unscheduled.length} 项委托没排期` : '今天的委托都排上了'),
            h('p', null, unscheduled.length
              ? '点击任意一项，选择开始与结束时间即可放进时间轴。'
              : `共 ${quests.length} 项委托已全部安排进时间轴。`)),
          h('button', {
            className: 'ghost small',
            disabled: !unscheduled.length,
            onClick: () => this.openScheduleQuestPlanForm(day, unscheduled.length ? unscheduled[0].id : ''),
          }, '快速排期第一项')),
        unscheduled.length ? poolList : empty('当天的每日委托都已经排进时间轴了。'));

      return h(F, null, timelinePanel, poolPanel);
    }
    renderSchedule(data) {
      const week = data || {};
      const day = week.day;
      const showDay = this.scheduleView === 'day' && !!day;
      const days = week.days || [];
      const totalPlans = days.reduce((acc, d) => acc + n(d.plan_count), 0);
      const totalPending = days.reduce((acc, d) => acc + n(d.unscheduled_count), 0);
      return h(F, null,
        h('section', { className: 'sch-bar' },
          h('div', { className: 'sch-bar-group' },
            h('div', { className: 'seg' },
              h('button', { className: showDay ? '' : 'is-on', onClick: () => this.changeScheduleWeek(week.week_start || week.today) }, '周表格'),
              h('button', { className: showDay ? 'is-on' : '', onClick: () => this.openTodayTimeline() }, '时间轴')),
            h('button', { className: 'ghost small', onClick: () => this.loadPage('schedule') }, '同步')),
          h('div', { className: 'sch-bar-group sch-nav' },
            showDay
              ? h(F, null,
                  h('button', { className: 'ghost small', title: '前一天', onClick: () => this.changeScheduleDay(day.prev_date) }, '‹'),
                  h('span', { className: 'sch-nav-label' }, `${day.date} · ${day.weekday_label}`),
                  h('button', { className: 'ghost small', title: '后一天', onClick: () => this.changeScheduleDay(day.next_date) }, '›'),
                  h('button', { className: 'ghost small', disabled: day.is_today, onClick: () => this.changeScheduleDay(day.today) }, '回到今天'))
              : h(F, null,
                  h('button', { className: 'ghost small', title: '上一周', onClick: () => this.changeScheduleWeek(week.prev_week_date) }, '‹'),
                  h('span', { className: 'sch-nav-label' }, week.week_label || ''),
                  h('button', { className: 'ghost small', title: '下一周', onClick: () => this.changeScheduleWeek(week.next_week_date) }, '›'),
                  h('button', { className: 'ghost small', disabled: week.is_current_week, onClick: () => this.changeScheduleWeek(week.today) }, '本周'))),
          h('div', { className: 'sch-scope' },
            h('div', { className: 'sch-stat' }, h('span', null, '本周安排'), h('b', null, totalPlans)),
            h('div', { className: 'sch-stat' }, h('span', null, '待排期'), h('b', null, showDay ? n((day.unscheduled_quests || []).length) : totalPending)))),
        showDay ? this.renderScheduleDay(day) : this.renderScheduleWeek(week));
    }

    renderPageContent() {
      if (this.state.loading) return h(LoadingPanel, { text: '正在读取星图数据...' });
      if (this.state.error) return h(ErrorPanel, { error: this.state.error });
      const data = this.state.pageData;
      switch (this.state.page) {
        case 'today': return this.renderToday(data);
        case 'quests': return this.renderQuests(data);
        case 'schedule': return this.renderSchedule(data);
        case 'legends': return this.renderLegends(data);
        case 'focus': return this.renderFocus(data);
        case 'rewards': return this.renderRewards(data);
        case 'states': return this.renderStates(data);
        case 'stats': return this.renderStats(data);
        case 'agent': return this.renderAgent(data);
        case 'settings': return this.renderSettings(data);
        default: return h(ErrorPanel, { error: '未知页面' });
      }
    }

    renderStartupPanel() {
      const results = this.state.boot?.startup_results || [];
      if (!results.length) return null;
      const latest = results[results.length - 1] || {};
      return h('section', { className: 'startup-notice' },
        h('div', { className: 'startup-notice-icon', 'aria-hidden': 'true' }, '↻'),
        h('div', null, h('b', null, `已自动补结算 ${results.length} 天`), h('p', null, `${latest.date || ''} · ${latest.day_title || '日终结算'} · 入池 ${fmtPoints(latest.points_banked)} 点`)),
        badge('已同步', 'gold')
      );
    }

    renderAgentEntry(entry) {
      const isAi = entry.actor === 'companion';
      const target = AGENT_TARGET_LABELS[entry.target_type] || entry.target_type || '';
      const detail = agentEntryDetail(entry);
      const when = String(entry.created_at || '').slice(5, 16);
      const canUndo = entry.undoable && !entry.undone;
      return h('article', { key: entry.id, className: `agent-entry ${isAi ? 'is-ai' : 'is-me'} ${entry.undone ? 'is-undone' : ''}` },
        h('div', { className: 'agent-entry-rail', 'aria-hidden': 'true' }, h('span', null, isAi ? '✳' : '•')),
        h('div', { className: 'agent-entry-card' },
          h('div', { className: 'agent-entry-head' },
            h('span', { className: `agent-actor ${isAi ? 'ai' : 'me'}` }, isAi ? '数字人' : '我'),
            h('b', null, agentActionLabel(entry)),
            target ? h('span', { className: 'agent-target' }, `${target}${entry.target_id != null ? ` #${entry.target_id}` : ''}`) : null,
            h('time', null, when)
          ),
          detail ? h('p', { className: 'agent-entry-detail' }, detail) : null,
          entry.undone
            ? h('div', { className: 'agent-entry-foot' },
                badge('已撤销'),
                entry.undo_note ? h('span', { className: 'muted' }, entry.undo_note) : null)
            : (canUndo
                ? h('div', { className: 'agent-entry-foot' },
                    h('button', { className: 'ghost small', onClick: () => this.confirmAgentUndo(entry) }, '撤销这次操作'))
                : h('div', { className: 'agent-entry-foot' }, h('span', { className: 'muted' }, '记录性操作（不支持撤销）')))
        )
      );
    }

    renderAgent(data) {
      const entries = Array.isArray(data) ? data : [];
      const filter = this.state.agentFilter || 'all';
      const visible = entries.filter((entry) => {
        if (filter === 'companion') return entry.actor === 'companion';
        if (filter === 'me') return entry.actor !== 'companion';
        if (filter === 'undoable') return entry.undoable && !entry.undone;
        return true;
      });
      const companionCount = entries.filter((entry) => entry.actor === 'companion').length;
      const undoableCount = entries.filter((entry) => entry.undoable && !entry.undone).length;
      const filters = [
        ['all', '全部'],
        ['companion', '数字人'],
        ['me', '我的改动'],
        ['undoable', '可撤销'],
      ];
      return h('div', { className: 'agent-page' },
        h('section', { className: 'agent-hero' },
          h('div', null,
            h('h3', null, '她做了什么，都在这里'),
            h('p', null, '每一次数字人的读写在两端都留痕：来源、改了什么、能不能还原。她动你的数据前一定会先征求确认，撤销按记录恢复原状，撤销本身也会留痕。')),
          h('div', { className: 'agent-stats' },
            h('div', null, h('b', null, String(companionCount)), h('span', null, '数字人操作')),
            h('div', null, h('b', null, String(entries.length - companionCount)), h('span', null, '我的操作')),
            h('div', null, h('b', null, String(undoableCount)), h('span', null, '可撤销'))
          )
        ),
        h('div', { className: 'agent-filter' },
          filters.map(([id, label]) => h('button', {
            key: id,
            className: this.state.agentFilter === id ? 'active' : '',
            onClick: () => this.setAgentFilter(id),
          }, label))
        ),
        visible.length
          ? h('div', { className: 'agent-timeline' }, visible.map((entry) => this.renderAgentEntry(entry)))
          : empty(entries.length ? '这个筛选下还没有记录。' : '还没有 AI 操作记录 —— 她在向着星里做的每一步都会出现在这里。')
      );
    }

    setAgentFilter(filter) {
      this.setState({ agentFilter: filter });
    }

    confirmAgentUndo(entry) {
      const who = entry.actor === 'companion' ? '数字人' : '你';
      this.setState({ modal: {
        title: '撤销这次操作？',
        body: h('div', { className: 'agent-undo-confirm' },
          h('p', null, `${who}在 ${entry.created_at || ''} 执行了「${agentActionLabel(entry)}」${agentEntryDetail(entry) ? `（${agentEntryDetail(entry)}）` : ''}。`),
          h('p', { className: 'muted' }, '撤销会按审计记录恢复原状，不会重算历史结算；撤销本身也会留一条记录。')
        ),
        actions: h(F, null,
          h('button', { onClick: () => this.closeModal() }, '先不撤销'),
          h('button', { className: 'primary', onClick: () => { this.closeModal(); this.undoAgentAction(entry.id); } }, '确认撤销')
        ),
      } });
    }

    async undoAgentAction(id) {
      await this.safe(async () => {
        await api.post(`/api/agent/audit/${id}/undo`);
        await this.loadPage('agent');
      }, '已撤销，恢复原状');
    }

    renderModal() {
      const m = this.state.modal;
      if (!m) return null;
      return h('div', { className: 'modal-backdrop' },
        h('div', { className: 'modal' },
          h('div', { className: 'modal-head' }, h('h2', null, m.title),
            h('button', { className: 'ghost icon-only', 'aria-label': '关闭弹窗', title: '关闭弹窗', onClick: () => this.closeModal() }, '✕')),
          h('div', { className: 'modal-body' }, m.body),
          h('div', { className: 'modal-actions' }, m.actions)
        )
      );
    }

    renderToasts() {
      return h('div', { id: 'toast-root', 'aria-live': 'polite' });
    }

    render() {
      const navItem = NAV.find(([id]) => id === this.state.page) || [];
      const pageLabel = navItem[1] || '今天从哪里开始？';
      const pageDescriptor = navItem[3] || '个人成长工作台';
      const boot = this.state.boot;
      const subTitle = boot ? `逻辑日 ${boot.date} · 本地数据已连接` : '正在连接本地星图...';
      return h(F, null,
        h('aside', { className: 'sidebar react-sidebar' },
          h('div', { className: 'brand' }, h('div', { className: 'brand-mark' }, '✦'), h('div', null, h('p', { className: 'brand-overline' }, 'PERSONAL SYSTEM'), h('h1', null, '向着星'), h('p', null, 'To the stars, through the days.'))),
          h('nav', null, NAV.map(([id, label, icon, descriptor]) => h('button', { key: id, className: this.state.page === id ? 'active' : '', onClick: () => this.loadPage(id) }, h('span', { className: 'nav-icon' }, icon), h('span', { className: 'nav-copy' }, h('b', null, label), h('small', null, descriptor)), h('i', { 'aria-hidden': 'true' }, '↗')))),
          h('div', { className: 'sidebar-signature' }, h('span', null, '01'), h('p', null, '把生活设计成一场值得参与的长期游戏。')),
          h('div', { className: 'sidebar-footer' }, h('button', { className: 'ghost', onClick: () => this.shutdown() }, h('span', null, '退出并记录关闭'), h('i', { 'aria-hidden': 'true' }, '⌁')))
        ),
        h('main', { className: `main react-main page-${this.state.page}` },
          h('header', { className: 'topbar page-topbar' },
            h('div', null, h('p', { className: 'eyebrow' }, `TO THE STARS / ${String(this.state.page).toUpperCase()}`), h('div', { className: 'page-title-line' }, h('h2', null, pageLabel), h('span', null, pageDescriptor)), h('p', null, subTitle)),
            h(Wallet, { wallet: this.state.wallet })
          ),
          this.renderStartupPanel(),
          h('section', { className: 'page active react-page' }, this.renderPageContent())
        ),
        this.renderModal(),
        this.renderToasts()
      );
    }
  }

  const root = ReactDOM.createRoot(document.getElementById('root'));
  root.render(h(StarApp));
})();
