window.UI = {
  esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, s => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[s]));
  },

  isTruthy(v) {
    return v === true || v === 1 || v === '1' || v === 'true' || v === 'True';
  },

  toast(msg, type = 'info') {
    const root = document.getElementById('toast-root');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  },

  modal(title, body, actions = '') {
    const root = document.getElementById('modal-root');
    root.innerHTML = `
      <div class="modal-backdrop">
        <div class="modal">
          <div class="modal-head">
            <h2>${UI.esc(title)}</h2>
            <button class="ghost" data-close-modal>关闭</button>
          </div>
          <div class="modal-body">${body}</div>
          <div class="modal-actions">${actions}</div>
        </div>
      </div>
    `;
    root.querySelector('[data-close-modal]').onclick = () => UI.closeModal();
  },

  closeModal() {
    document.getElementById('modal-root').innerHTML = '';
  },

  formData(form) {
    return Object.fromEntries(new FormData(form).entries());
  },

  empty(text) {
    return `<div class="empty">${UI.esc(text)}</div>`;
  },

  table(rows = [], columns = []) {
    if (!rows || !rows.length) return UI.empty('暂无数据');

    return `
      <table>
        <thead>
          <tr>
            ${columns.map(c => `<th>${UI.esc(c.label)}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              ${columns.map(c => `<td>${UI.esc(row[c.key] ?? '')}</td>`).join('')}
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  },

  wallet(w) {
    return `
      <div class="wallet-card">
        <span>历练点池</span>
        <b>${Number(w.practice_points || 0).toFixed(1)}</b>
      </div>
      <div class="wallet-card">
        <span>成长点池</span>
        <b>${Number(w.growth_points || 0).toFixed(1)}</b>
      </div>
    `;
  },

  questCard(q, opts = {}) {
    const isCompleted = UI.isTruthy(q.is_completed);
    const completedClass = isCompleted ? 'completed done-card' : '';

    return `
      <article
        class="card quest ${completedClass}"
        data-completed="${isCompleted ? '1' : '0'}"
        style="--accent:${q.difficulty_color || '#64748B'}"
      >
        <div class="rarity"></div>

        <div class="card-head">
          <div>
            <h3>${UI.esc(q.title)}</h3>
            <p class="muted">${UI.esc(q.description || '没有描述')}</p>
          </div>
          <strong>+${Number(q.points || 0).toFixed(1)} 历练点</strong>
        </div>

        <div class="badges">
          ${(q.badges || []).map(b => `<span class="badge">${UI.esc(b)}</span>`).join('')}
        </div>

        <div class="meta">
          <span>${UI.esc(q.difficulty_name || q.difficulty)}</span>
          <span>${UI.esc(q.category || '未分类')}</span>
          <span>已入池 ${Number(q.banked_points || 0).toFixed(1)}</span>
        </div>

        <div class="actions">
          <label class="check">
            <input
              type="checkbox"
              ${isCompleted ? 'checked' : ''}
              data-action="quest-complete"
              data-id="${q.id}"
            >
            完成
          </label>

          ${opts.edit ? `<button class="ghost" data-action="quest-edit" data-id="${q.id}">编辑</button>` : ''}
          ${opts.edit ? `<button class="danger ghost" data-action="quest-delete" data-id="${q.id}">删除</button>` : ''}
        </div>
      </article>
    `;
  },

  legendCard(l) {
    const progress = l.progress || { done: 0, total: 0 };
    const isCompleted =
      l.status === 'completed' ||
      l.status === '已完成' ||
      UI.isTruthy(l.points_awarded) ||
      (Number(progress.total || 0) > 0 && Number(progress.done || 0) >= Number(progress.total || 0));

    const completedClass = isCompleted ? 'completed done-card' : '';
    const pct = progress.total ? Math.round(progress.done / progress.total * 100) : 0;

    return `
      <article
        class="card legend ${completedClass}"
        data-id="${l.id}"
        data-completed="${isCompleted ? '1' : '0'}"
      >
        <div class="card-head">
          <div>
            <h3>${UI.esc(l.title)}</h3>
            <p class="muted">${UI.esc(l.content || '无描述')}</p>
          </div>
          <strong>+${Number(l.growth_points || 0).toFixed(1)} 成长点</strong>
        </div>

        <div class="badges">
          <span class="badge gold">${UI.esc(l.difficulty_name || l.difficulty || '')}</span>
          <span class="badge">${UI.esc(l.status || '')}</span>
          <span class="badge">截止 ${UI.esc(l.deadline || '-')}</span>
          <span class="badge">剩余 ${l.remaining_days ?? '-'} 天</span>
        </div>

        <div class="progress">
          <span style="width:${pct}%"></span>
        </div>

        <p class="muted">指标 ${progress.done}/${progress.total}</p>

        <div class="indicator-list">
          ${(l.indicators || []).map(i => {
            const done = UI.isTruthy(i.is_completed);
            return `
              <label class="indicator ${done ? 'done' : ''}">
                <input
                  type="checkbox"
                  ${done ? 'checked' : ''}
                  data-action="indicator-complete"
                  data-id="${i.id}"
                >
                ${UI.esc(i.title)}
              </label>
            `;
          }).join('')}
        </div>

        <div class="actions">
          <button class="small ghost" data-action="legend-add-indicator" data-id="${l.id}">新增指标</button>
          <button class="small ghost" data-action="legend-edit" data-id="${l.id}">编辑</button>
          <button class="small danger" data-action="legend-delete" data-id="${l.id}">归档</button>
        </div>
      </article>
    `;
  },
};