(function () {
  const STORAGE_KEY = 'to-the-stars-focus-timer-v1';

  function clamp(n, min, max) {
    n = Number(n);
    if (!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(max, Math.round(n)));
  }

  function fmt(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function fmtLong(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h) return `${h} 小时 ${m} 分钟`;
    return `${m} 分钟`;
  }

  function toLocalString(date) {
    const d = date instanceof Date ? date : new Date(date);
    const pad = (v) => String(v).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function optionList(categories, selected) {
    const list = categories?.length ? categories : ['实践', '知识', '学习', '工作', '其他', '未分类'];
    return list.map((c) => `<option value="${UI.esc(c)}" ${c === selected ? 'selected' : ''}>${UI.esc(c)}</option>`).join('');
  }

  function sessionLine(s) {
    return `
      <article class="focus-session-card">
        <div>
          <b>${UI.esc(s.category || '未分类')}</b>
          <span class="muted">${UI.esc(s.started_at || '')}</span>
          ${s.description ? `<p>${UI.esc(s.description)}</p>` : `<p class="muted">没有描述</p>`}
        </div>
        <strong>${UI.esc(s.duration_label || fmt(s.duration_seconds))}</strong>
      </article>
    `;
  }

  const FocusPage = {
    state: {
      mode: 'idle',
      plannedSeconds: 30 * 60,
      remainingSeconds: 30 * 60,
      accumulatedSeconds: 0,
      segmentStartedMs: null,
      startedAt: null,
      endedAt: null,
      todayStoredSeconds: 0,
      sessions: [],
      categories: [],
      presets: [15, 25, 30, 45, 60],
      category: '知识',
      description: '',
      timerId: null,
      loadedOnce: false,
      saving: false,
    },

    async load() {
      const data = await API.get('/api/focus/today');
      this.state.todayStoredSeconds = Number(data.today_seconds || 0);
      this.state.sessions = data.sessions || [];
      this.state.categories = data.categories || [];
      this.state.presets = data.presets || [15, 25, 30, 45, 60];
      if (!this.state.loadedOnce) {
        this.restore();
        this.state.loadedOnce = true;
      }
      this.ensureTicker();
      this.render();
    },

    storageSnapshot() {
      const s = this.state;
      if (!['running', 'paused', 'finished'].includes(s.mode)) return null;
      return {
        mode: s.mode,
        plannedSeconds: s.plannedSeconds,
        remainingSeconds: s.remainingSeconds,
        accumulatedSeconds: this.activeSeconds(),
        segmentStartedMs: s.mode === 'running' ? s.segmentStartedMs : null,
        startedAt: s.startedAt ? s.startedAt.toISOString() : null,
        endedAt: s.endedAt ? s.endedAt.toISOString() : null,
        category: s.category,
        description: s.description,
      };
    },

    persist() {
      const snap = this.storageSnapshot();
      if (!snap) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, JSON.stringify(snap));
    },

    restore() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const saved = JSON.parse(raw);
        if (!saved || !['running', 'paused', 'finished'].includes(saved.mode)) return;

        const planned = clamp(Number(saved.plannedSeconds || 1800) / 60, 1, 240) * 60;
        this.state.mode = saved.mode;
        this.state.plannedSeconds = planned;
        this.state.startedAt = saved.startedAt ? new Date(saved.startedAt) : new Date();
        this.state.endedAt = saved.endedAt ? new Date(saved.endedAt) : null;
        this.state.category = saved.category || this.state.category || '未分类';
        this.state.description = saved.description || '';

        if (saved.mode === 'running') {
          const segStart = Number(saved.segmentStartedMs || Date.now());
          const before = Number(saved.accumulatedSeconds || 0);
          const active = Math.min(planned, before + Math.max(0, Math.floor((Date.now() - segStart) / 1000)));
          this.state.accumulatedSeconds = active;
          this.state.segmentStartedMs = active >= planned ? null : Date.now();
          this.state.remainingSeconds = Math.max(0, planned - active);
          if (active >= planned) this.finish(true);
        } else if (saved.mode === 'paused') {
          const active = Math.min(planned, Number(saved.accumulatedSeconds || 0));
          this.state.accumulatedSeconds = active;
          this.state.remainingSeconds = Math.max(0, planned - active);
          this.state.segmentStartedMs = null;
        } else if (saved.mode === 'finished') {
          this.state.accumulatedSeconds = planned;
          this.state.remainingSeconds = 0;
          this.state.segmentStartedMs = null;
          this.state.endedAt = this.state.endedAt || new Date();
        }
      } catch (err) {
        console.warn('focus timer restore failed', err);
        localStorage.removeItem(STORAGE_KEY);
      }
    },

    activeSeconds() {
      const s = this.state;
      if (s.mode === 'running' && s.segmentStartedMs) {
        return Math.min(s.plannedSeconds, s.accumulatedSeconds + Math.max(0, Math.floor((Date.now() - s.segmentStartedMs) / 1000)));
      }
      if (s.mode === 'finished') return s.plannedSeconds;
      return Math.min(s.plannedSeconds, Number(s.accumulatedSeconds || 0));
    },

    displaySeconds() {
      const s = this.state;
      if (s.mode === 'idle') return s.plannedSeconds;
      if (s.mode === 'finished') return 0;
      return Math.max(0, s.plannedSeconds - this.activeSeconds());
    },

    todayPreviewSeconds() {
      const s = this.state;
      if (['running', 'paused', 'finished'].includes(s.mode)) return s.todayStoredSeconds + this.activeSeconds();
      return s.todayStoredSeconds;
    },

    statusText() {
      const mode = this.state.mode;
      if (mode === 'running') return '专注中 · 当前未保存，完成并结算后计入统计';
      if (mode === 'paused') return '已暂停 · 继续后从当前剩余时间开始';
      if (mode === 'finished') return '完成！请保存本次专注事件';
      return '准备开始 · 取消不计入统计，完成保存后写入专注记录';
    },

    start() {
      const input = document.getElementById('focus-minutes');
      const minutes = clamp(input?.value || this.state.plannedSeconds / 60, 1, 240);
      this.state.mode = 'running';
      this.state.plannedSeconds = minutes * 60;
      this.state.remainingSeconds = minutes * 60;
      this.state.accumulatedSeconds = 0;
      this.state.segmentStartedMs = Date.now();
      this.state.startedAt = new Date();
      this.state.endedAt = null;
      this.state.description = '';
      this.persist();
      this.ensureTicker();
      this.render();
    },

    pause() {
      if (this.state.mode !== 'running') return;
      this.state.accumulatedSeconds = this.activeSeconds();
      this.state.remainingSeconds = Math.max(0, this.state.plannedSeconds - this.state.accumulatedSeconds);
      this.state.segmentStartedMs = null;
      this.state.mode = 'paused';
      this.persist();
      this.render();
    },

    resume() {
      if (this.state.mode !== 'paused') return;
      this.state.mode = 'running';
      this.state.segmentStartedMs = Date.now();
      this.persist();
      this.ensureTicker();
      this.render();
    },

    cancel() {
      if (!confirm('取消后本次专注不会计入统计，确定取消吗？')) return;
      this.resetToIdle(false);
      UI.toast('已取消本轮专注，本次不会计入统计。');
    },

    finish(fromRestore = false) {
      this.state.mode = 'finished';
      this.state.accumulatedSeconds = this.state.plannedSeconds;
      this.state.remainingSeconds = 0;
      this.state.segmentStartedMs = null;
      this.state.endedAt = this.state.endedAt || new Date();
      this.stopTicker();
      this.persist();
      if (!fromRestore) UI.toast('本轮专注完成，请保存记录。');
      this.render();
    },

    resetToIdle(keepLast = true) {
      const planned = keepLast ? this.state.plannedSeconds : 30 * 60;
      this.stopTicker();
      this.state.mode = 'idle';
      this.state.plannedSeconds = planned;
      this.state.remainingSeconds = planned;
      this.state.accumulatedSeconds = 0;
      this.state.segmentStartedMs = null;
      this.state.startedAt = null;
      this.state.endedAt = null;
      this.state.description = '';
      localStorage.removeItem(STORAGE_KEY);
      this.render();
    },

    discard() {
      if (!confirm('放弃后本次专注不会计入统计，确定放弃记录吗？')) return;
      this.resetToIdle(true);
    },

    async saveSession() {
      if (this.state.saving) return;
      const category = document.getElementById('focus-settle-category')?.value || this.state.category || '未分类';
      const description = document.getElementById('focus-description')?.value || '';
      this.state.saving = true;
      this.render();
      try {
        const payload = {
          started_at: toLocalString(this.state.startedAt || new Date()),
          ended_at: toLocalString(this.state.endedAt || new Date()),
          planned_minutes: Math.round(this.state.plannedSeconds / 60),
          duration_seconds: this.state.plannedSeconds,
          category,
          description,
        };
        const result = await API.post('/api/focus/sessions', payload);
        this.state.todayStoredSeconds = Number(result.today_seconds || 0);
        localStorage.removeItem(STORAGE_KEY);
        UI.toast('专注记录已保存。');
        this.state.mode = 'idle';
        this.state.remainingSeconds = this.state.plannedSeconds;
        this.state.accumulatedSeconds = 0;
        this.state.startedAt = null;
        this.state.endedAt = null;
        this.state.description = '';
        await this.load();
      } finally {
        this.state.saving = false;
        this.render();
      }
    },

    adjustMinutes(delta) {
      if (this.state.mode !== 'idle') return;
      const current = clamp(this.state.plannedSeconds / 60, 1, 240);
      const next = clamp(current + delta, 1, 240);
      this.state.plannedSeconds = next * 60;
      this.state.remainingSeconds = next * 60;
      this.render();
    },

    setPreset(minutes) {
      if (this.state.mode !== 'idle') return;
      const next = clamp(minutes, 1, 240);
      this.state.plannedSeconds = next * 60;
      this.state.remainingSeconds = next * 60;
      this.render();
    },

    ensureTicker() {
      if (this.state.timerId || this.state.mode !== 'running') return;
      this.state.timerId = setInterval(() => {
        const active = this.activeSeconds();
        this.state.remainingSeconds = Math.max(0, this.state.plannedSeconds - active);
        if (active >= this.state.plannedSeconds) {
          this.finish();
          return;
        }
        this.persist();
        this.updateLiveBits();
      }, 250);
    },

    stopTicker() {
      if (this.state.timerId) clearInterval(this.state.timerId);
      this.state.timerId = null;
    },

    updateLiveBits() {
      const timer = document.getElementById('focus-timer-value');
      const today = document.getElementById('focus-today-live');
      const active = document.getElementById('focus-active-live');
      if (timer) timer.textContent = fmt(this.displaySeconds());
      if (today) today.textContent = fmt(this.todayPreviewSeconds());
      if (active) active.textContent = fmt(this.activeSeconds());
    },

    renderActions() {
      const mode = this.state.mode;
      if (mode === 'running') {
        return `<button class="ghost" data-action="pause">暂停</button><button class="danger" data-action="cancel">取消</button>`;
      }
      if (mode === 'paused') {
        return `<button data-action="resume">继续</button><button class="danger" data-action="cancel">取消</button>`;
      }
      if (mode === 'finished') {
        return `<button data-action="save" ${this.state.saving ? 'disabled' : ''}>保存记录</button><button class="ghost" data-action="discard">放弃记录</button>`;
      }
      return `<button data-action="start">开始专注</button>`;
    },

    renderSettlement() {
      if (this.state.mode !== 'finished') return '';
      return `
        <section class="panel focus-finish-panel">
          <div class="focus-finish-title">完成！</div>
          <div class="grid cols focus-mini-stats">
            <div><span>本次专注</span><b>${fmt(this.state.plannedSeconds)}</b></div>
            <div><span>保存后今日专注</span><b>${fmt(this.state.todayStoredSeconds + this.state.plannedSeconds)}</b></div>
            <div><span>开始 / 结束</span><b>${UI.esc(toLocalString(this.state.startedAt))} → ${UI.esc(toLocalString(this.state.endedAt))}</b></div>
          </div>
          <div class="form focus-settle-form">
            <label>专注分类
              <select id="focus-settle-category">${optionList(this.state.categories, this.state.category)}</select>
            </label>
            <label>专注事件描述
              <textarea id="focus-description" placeholder="这轮专注做了什么？例如：完成英语阅读第 3 篇。">${UI.esc(this.state.description || '')}</textarea>
            </label>
            <div class="row">
              <button data-action="save" ${this.state.saving ? 'disabled' : ''}>保存专注事件</button>
              <button class="ghost" data-action="discard">放弃记录</button>
            </div>
          </div>
        </section>
      `;
    },

    render() {
      const el = document.getElementById('page-focus');
      if (!el) return;
      const s = this.state;
      const minutes = Math.round(s.plannedSeconds / 60);
      const disabled = s.mode !== 'idle' ? 'disabled' : '';
      const sessions = s.sessions?.length ? s.sessions.map(sessionLine).join('') : UI.empty('今天还没有保存专注记录。完成一轮番茄钟后会出现在这里。');

      el.innerHTML = `
        <div class="focus-hero panel">
          <div>
            <p class="eyebrow">FOCUS TIMER · 番茄钟</p>
            <h3>把一次行动，落成一条专注记录</h3>
            <p class="muted">完成后进入结算页；保存后才计入统计。暂停不会计时，取消不会入库。</p>
          </div>
          <div class="focus-today-card">
            <span>今日专注</span>
            <b id="focus-today-live">${fmt(this.todayPreviewSeconds())}</b>
            <small>逻辑日统计，凌晨 4 点切换</small>
          </div>
        </div>

        <div class="focus-layout">
          <section class="panel focus-clock-panel ${s.mode}">
            <div class="focus-status">${UI.esc(this.statusText())}</div>
            <div id="focus-timer-value" class="focus-timer">${fmt(this.displaySeconds())}</div>
            <div class="focus-orbit"></div>
            <div class="grid cols focus-mini-stats">
              <div><span>本轮计划</span><b>${fmt(s.plannedSeconds)}</b></div>
              <div><span>当前已专注</span><b id="focus-active-live">${fmt(this.activeSeconds())}</b></div>
              <div><span>已保存今日</span><b>${fmt(s.todayStoredSeconds)}</b></div>
            </div>
            <div class="focus-actions">${this.renderActions()}</div>
          </section>

          <aside class="panel focus-control-panel">
            <h3>倒计时设置</h3>
            <div class="focus-stepper">
              <button class="ghost" data-action="adjust" data-delta="-5" ${disabled}>-5</button>
              <label>
                分钟
                <input id="focus-minutes" type="number" min="1" max="240" value="${minutes}" ${disabled}>
              </label>
              <button class="ghost" data-action="adjust" data-delta="5" ${disabled}>+5</button>
            </div>
            <div class="focus-presets">
              ${s.presets.map((p) => `<button class="ghost ${p === minutes ? 'active' : ''}" data-action="preset" data-minutes="${p}" ${disabled}>${p} 分钟</button>`).join('')}
            </div>
            <label class="focus-category-label">默认分类
              <select id="focus-category" ${s.mode === 'running' || s.mode === 'paused' ? 'disabled' : ''}>${optionList(s.categories, s.category)}</select>
            </label>
            <div class="focus-help">
              <b>规则</b>
              <p>开始后可以暂停或取消；倒计时自然结束后进入“完成”结算区，填写分类和描述后保存。</p>
              <p>只有保存后的专注事件会进入“统计复盘”的每日时长、总时长和事件记录。</p>
            </div>
          </aside>
        </div>

        ${this.renderSettlement()}

        <section class="panel">
          <div class="between"><h3>今日专注事件</h3><span class="badge">${s.sessions.length} 条</span></div>
          <div class="focus-session-list">${sessions}</div>
        </section>
      `;

      el.onclick = (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        if (action === 'start') this.start();
        if (action === 'pause') this.pause();
        if (action === 'resume') this.resume();
        if (action === 'cancel') this.cancel();
        if (action === 'save') this.saveSession();
        if (action === 'discard') this.discard();
        if (action === 'adjust') this.adjustMinutes(Number(btn.dataset.delta || 0));
        if (action === 'preset') this.setPreset(Number(btn.dataset.minutes || 30));
      };

      const minuteInput = document.getElementById('focus-minutes');
      if (minuteInput) {
        minuteInput.onchange = () => {
          if (this.state.mode !== 'idle') return;
          const next = clamp(minuteInput.value, 1, 240);
          this.state.plannedSeconds = next * 60;
          this.state.remainingSeconds = next * 60;
          this.render();
        };
      }

      const category = document.getElementById('focus-category');
      if (category) {
        category.onchange = () => {
          this.state.category = category.value || '未分类';
          this.persist();
        };
      }

      const settleCategory = document.getElementById('focus-settle-category');
      if (settleCategory) {
        settleCategory.onchange = () => {
          this.state.category = settleCategory.value || '未分类';
          this.persist();
        };
      }

      const desc = document.getElementById('focus-description');
      if (desc) {
        desc.oninput = () => {
          this.state.description = desc.value;
          this.persist();
        };
      }
    },
  };

  window.addEventListener('beforeunload', (e) => {
    if (['running', 'paused', 'finished'].includes(FocusPage.state.mode)) {
      FocusPage.persist();
      e.preventDefault();
      e.returnValue = '';
    }
  });

  App.pages.focus = FocusPage;
})();
