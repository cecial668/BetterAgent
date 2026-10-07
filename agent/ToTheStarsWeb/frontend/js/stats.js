(function () {
  function fmtDuration(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function renderFocusChart(daily = []) {
    if (!daily.length) return UI.empty('暂无专注统计数据');
    const max = Math.max(...daily.map((d) => Number(d.seconds || 0)), 1);
    return `
      <div class="focus-chart" aria-label="每日专注时长图表">
        ${daily.map((d) => {
          const seconds = Number(d.seconds || 0);
          const height = seconds ? Math.max(8, Math.round(seconds / max * 100)) : 4;
          const label = String(d.date || '').slice(5);
          return `
            <div class="focus-chart-item" title="${UI.esc(d.date)} · ${UI.esc(d.label || fmtDuration(seconds))}">
              <div class="focus-bar-wrap"><span class="focus-bar" style="height:${height}%"></span></div>
              <small>${UI.esc(label)}</small>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  function renderFocusStats(focus) {
    const daily = focus.daily || [];
    const sum = daily.reduce((acc, d) => acc + Number(d.seconds || 0), 0);
    const avg = daily.length ? Math.round(sum / daily.length) : 0;
    const sessions = (focus.sessions || []).slice(0, 80).map((s) => ({
      started_at: s.started_at || '',
      business_date: s.business_date || '',
      duration_label: s.duration_label || fmtDuration(s.duration_seconds),
      category: s.category || '未分类',
      description: s.description || '',
    }));

    return `
      <section class="panel focus-stats-panel">
        <div class="between">
          <div>
            <h3>专注统计</h3>
            <p class="muted">来自番茄钟保存后的专注事件；取消或未保存的计时不纳入统计。</p>
          </div>
          <span class="badge gold">近 ${daily.length || 14} 日</span>
        </div>
        <div class="grid cols focus-stat-grid">
          <div class="focus-stat"><span>今日专注</span><b>${fmtDuration(focus.today_seconds)}</b></div>
          <div class="focus-stat"><span>历史总专注</span><b>${fmtDuration(focus.total_seconds)}</b></div>
          <div class="focus-stat"><span>最近日均</span><b>${fmtDuration(avg)}</b></div>
        </div>
        ${renderFocusChart(daily)}
      </section>
      <section class="panel">
        <h3>专注事件记录</h3>
        ${UI.table(sessions, [
          { key: 'started_at', label: '发生时间' },
          { key: 'business_date', label: '业务日' },
          { key: 'duration_label', label: '时长' },
          { key: 'category', label: '分类' },
          { key: 'description', label: '描述' },
        ])}
      </section>
    `;
  }

  App.pages.stats = {
    async load() {
      const [sum, tx, st, sett, cat, leg, focus] = await Promise.all([
        API.get('/api/stats/summary'),
        API.get('/api/stats/transactions'),
        API.get('/api/stats/states'),
        API.get('/api/stats/settlements'),
        API.get('/api/stats/quests-by-category'),
        API.get('/api/stats/legend-progress'),
        API.get('/api/stats/focus?days=14'),
      ]);

      const el = document.getElementById('page-stats');
      el.innerHTML = `
        <div class="grid cols">
          <div class="panel">
            <h3>完成率</h3>
            <p class="points">${Number(sum.completion_rate).toFixed(1)}%</p>
            <p class="muted">${sum.completion_done_days}/${sum.completion_total_days} 个普通日达成</p>
          </div>
          <div class="panel"><h3>当前余额</h3>${UI.wallet(sum.wallet)}</div>
          <div class="panel"><h3>当前资源</h3><p>委托 ${sum.active_quests} · 传说 ${sum.legend_count} · 奖励 ${sum.reward_count}</p></div>
        </div>

        ${renderFocusStats(focus)}

        <div class="panel">
          <h3>最近结算</h3>
          ${UI.table(sett.slice(0, 20), [
            { key: 'date', label: '日期' },
            { key: 'day_title', label: '称号' },
            { key: 'total_points', label: '完成点数' },
            { key: 'points_banked', label: '入池' },
            { key: 'state_bonus', label: '状态奖励' },
          ])}
        </div>
        <div class="panel">
          <h3>点数流水</h3>
          ${UI.table(tx.slice(0, 50), [
            { key: 'created_at', label: '时间' },
            { key: 'point_type', label: '类型' },
            { key: 'amount', label: '变化' },
            { key: 'reason', label: '原因' },
            { key: 'balance_after', label: '余额' },
          ])}
        </div>
        <div class="grid cols">
          <div class="panel">
            <h3>状态记录</h3>
            ${UI.table(st.slice(0, 20), [
              { key: 'date', label: '日期' },
              { key: 'rating', label: '评价' },
              { key: 'social_type', label: '社交' },
              { key: 'energy', label: '能量' },
              { key: 'review_text', label: '复盘' },
            ])}
          </div>
          <div class="panel">
            <h3>分类统计</h3>
            ${UI.table(cat, [
              { key: 'category', label: '分类' },
              { key: 'count', label: '数量' },
              { key: 'points', label: '点数' },
            ])}
          </div>
        </div>
        <div class="panel">
          <h3>传说进度</h3>
          ${UI.table(leg, [
            { key: 'title', label: '任务' },
            { key: 'status', label: '状态' },
            { key: 'deadline', label: '截止' },
            { key: 'done', label: '完成指标' },
            { key: 'total', label: '总指标' },
          ])}
        </div>
      `;
    },
  };
})();
