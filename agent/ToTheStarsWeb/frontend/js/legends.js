App.pages.legends = {
  async load() {
    const rows = await API.get('/api/legends');
    const el = document.getElementById('page-legends');

    el.innerHTML = `
      <div class="toolbar">
        <button data-action="new-legend">创建传说任务</button>
        <span class="muted">长期目标 ${rows.length} 项</span>
      </div>

      <div class="grid cols">
        ${rows.length ? rows.map(l => UI.legendCard(l)).join('') : UI.empty('暂无传说任务')}
      </div>
    `;

    el.onclick = async (e) => {
      const a = e.target.dataset.action;
      const id = e.target.dataset.id;

      if (!a) return;

      if (a === 'new-legend') {
        return Legends.openForm();
      }

      if (a === 'legend-edit') {
        return Legends.openForm(rows.find(x => String(x.id) === String(id)));
      }

      if (a === 'indicator-complete') {
        await API.post(`/api/legends/indicators/${id}/complete`, {
          completed: e.target.checked,
        });
        UI.toast('指标已更新');
        return App.setPage('legends');
      }

      if (a === 'legend-add-indicator') {
        UI.modal(
          '新增指标',
          `
          <form id="ind-form" class="form">
            <label>
              指标名称
              <input name="title" required>
            </label>
            <label>
              指标描述
              <textarea name="description"></textarea>
            </label>
          </form>
          `,
          `<button id="save-ind">保存</button>`
        );

        document.getElementById('save-ind').onclick = async () => {
          const d = UI.formData(document.getElementById('ind-form'));
          await API.post(`/api/legends/${id}/indicators`, d);
          UI.closeModal();
          UI.toast('指标已新增');
          App.setPage('legends');
        };

        return;
      }

      if (a === 'legend-delete') {
        if (confirm('归档该传说任务？')) {
          await API.del(`/api/legends/${id}`);
          UI.toast('已归档');
          return App.setPage('legends');
        }
      }
    };
  },
};

window.Legends = {
  openForm(l = null) {
    const diff = App.state.constants.legend_difficulties || {};

    UI.modal(
      l ? '编辑传说任务' : '创建传说任务',
      `
      <form id="legend-form" class="form">
        <label>
          名称
          <input name="title" value="${UI.esc(l?.title || '')}" required>
        </label>

        <label>
          内容
          <textarea name="content">${UI.esc(l?.content || '')}</textarea>
        </label>

        <label>
          难度
          <select name="difficulty">
            ${Object.keys(diff).map(k => `
              <option value="${k}" ${l?.difficulty === k ? 'selected' : ''}>
                ${k} · ${diff[k].name}（${diff[k].points}点）
              </option>
            `).join('')}
          </select>
        </label>

        <label>
          截止日期
          <input type="date" name="deadline" value="${UI.esc(l?.deadline || '')}" required>
        </label>

        ${l ? '' : `
          <label>
            初始指标（每行一个）
            <textarea name="indicators"></textarea>
          </label>
        `}
      </form>
      `,
      `<button id="save-legend">保存</button>`
    );

    document.getElementById('save-legend').onclick = async () => {
      const d = UI.formData(document.getElementById('legend-form'));

      if (!l) {
        d.indicators = (d.indicators || '')
          .split('\n')
          .map(x => x.trim())
          .filter(Boolean);
      }

      if (l) {
        await API.put(`/api/legends/${l.id}`, d);
      } else {
        await API.post('/api/legends', d);
      }

      UI.closeModal();
      UI.toast('传说任务已保存');
      App.setPage('legends');
    };
  },
};