window.QuestPage = App.pages.quests = {
  async load() {
    const el = document.getElementById('page-quests');
    const rows = await API.get('/api/quests');

    el.innerHTML = `
      <div class="toolbar">
        <div class="row">
          <button data-action="new-quest">新建每日委托</button>
          <button class="ghost" data-action="refresh">刷新</button>
        </div>
        <span class="muted">当前委托池 ${rows.length} 项</span>
      </div>

      <div class="grid cols">
        ${rows.length ? rows.map(q => UI.questCard(q, { edit: true })).join('') : UI.empty('暂无委托')}
      </div>
    `;

    el.onclick = async (e) => {
      const a = e.target.dataset.action;
      const id = e.target.dataset.id;

      if (!a) return;

      if (a === 'new-quest') {
        return QuestPage.openForm();
      }

      if (a === 'refresh') {
        return App.setPage('quests');
      }

      if (a === 'quest-complete') {
        await API.post(`/api/quests/${id}/complete`, {
          completed: e.target.checked,
        });
        return App.setPage('quests');
      }

      if (a === 'quest-edit') {
        const q = rows.find(x => String(x.id) === String(id));
        return QuestPage.openForm(q);
      }

      if (a === 'quest-delete') {
        if (confirm('删除前会写入历史记录，确定删除？')) {
          await API.del(`/api/quests/${id}`);
          UI.toast('已删除');
          return App.setPage('quests');
        }
      }
    };
  },

  openForm(q = null) {
    const diff = App.state.constants.difficulties || {};
    const baseCats = App.state.constants.categories || [];

    const currentCategory = q?.category || baseCats[0] || '未分类';

    const categories = [...baseCats];
    if (currentCategory && !categories.includes(currentCategory)) {
      categories.unshift(currentCategory);
    }

    const isCustomCategory = currentCategory && !baseCats.includes(currentCategory);

    const difficultyOptions = Object.keys(diff).map(k => {
      return `
        <option value="${k}" ${q?.difficulty === k ? 'selected' : ''}>
          ${k} · ${diff[k].name}（${diff[k].points}点）
        </option>
      `;
    }).join('');

    const categoryOptions = categories.map(c => {
      return `
        <option value="${UI.esc(c)}" ${currentCategory === c ? 'selected' : ''}>
          ${UI.esc(c)}
        </option>
      `;
    }).join('');

    UI.modal(
      q ? '编辑委托' : '新建委托',
      `
      <form id="quest-form" class="form">
        <label>
          名称
          <input name="title" value="${UI.esc(q?.title || '')}" required>
        </label>

        <label>
          描述
          <textarea name="description">${UI.esc(q?.description || '')}</textarea>
        </label>

        <label>
          难度
          <select name="difficulty">
            ${difficultyOptions}
          </select>
        </label>

        <label>
          分类
          <select name="category_select" id="quest-category-select">
            ${categoryOptions}
            <option value="__custom__" ${isCustomCategory ? 'selected' : ''}>自定义分类...</option>
          </select>
        </label>

        <label id="custom-category-wrap" class="${isCustomCategory ? '' : 'hidden'}">
          自定义分类名称
          <input name="category_custom" value="${isCustomCategory ? UI.esc(currentCategory) : ''}" placeholder="例如：雅思、论文、健身、申请材料">
        </label>

        <label class="checkbox-line">
          <input type="checkbox" name="is_required" ${q?.is_required ? 'checked' : ''}>
          <span>
            <b>必要委托</b>
            <small>普通日必须完成，否则当天每日委托判定失败</small>
          </span>
        </label>

        <label class="checkbox-line">
          <input type="checkbox" name="is_recurring" ${q?.is_recurring ? 'checked' : ''}>
          <span>
            <b>日常委托</b>
            <small>完成并日终结算后，第二天会自动刷新一份未完成的新委托</small>
          </span>
        </label>
      </form>
      `,
      `
      <button id="save-quest">保存</button>
      `
    );

    const categorySelect = document.getElementById('quest-category-select');
    const customWrap = document.getElementById('custom-category-wrap');

    categorySelect.onchange = () => {
      customWrap.classList.toggle('hidden', categorySelect.value !== '__custom__');

      if (categorySelect.value === '__custom__') {
        const input = document.querySelector('#quest-form [name="category_custom"]');
        setTimeout(() => input?.focus(), 0);
      }
    };

    document.getElementById('save-quest').onclick = async () => {
      const f = document.getElementById('quest-form');
      const data = UI.formData(f);

      let category = data.category_select;

      if (category === '__custom__') {
        category = (data.category_custom || '').trim();
      }

      if (!category) {
        UI.toast('请填写分类名称', 'error');
        return;
      }

      data.category = category;
      data.is_required = f.is_required.checked;
      data.is_recurring = f.is_recurring.checked;

      delete data.category_select;
      delete data.category_custom;

      if (q) {
        await API.put(`/api/quests/${q.id}`, data);
      } else {
        await API.post('/api/quests', data);
      }

      UI.closeModal();
      UI.toast('委托已保存');
      App.setPage(App.state.page);
    };
  },
};