window.RewardPage = App.pages.rewards = {
  currentTab: 'shop',

  async load() {
    const el = document.getElementById('page-rewards');
    const rows = await API.get('/api/rewards');
    const purchases = await API.get('/api/rewards/purchases');
    const wallet = await API.get('/api/wallet');

    const decoratedRows = rows
      .map(r => {
        const info = RewardPage.progressInfo(r, wallet);

        return {
          ...r,
          _progressPercent: info.percent,
          _sortGroup: RewardPage.sortGroup(r),
        };
      })
      .sort((a, b) => {
        if (a._sortGroup !== b._sortGroup) {
          return a._sortGroup - b._sortGroup;
        }

        if (b._progressPercent !== a._progressPercent) {
          return b._progressPercent - a._progressPercent;
        }

        return String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN');
      });

    const sortedPurchases = purchases.slice().sort((a, b) => {
      const ga = a.outbound_status === 'shipped' ? 1 : 0;
      const gb = b.outbound_status === 'shipped' ? 1 : 0;
      if (ga !== gb) return ga - gb;
      return String(b.purchased_at || '').localeCompare(String(a.purchased_at || ''));
    });

    const pendingCount = purchases.filter(p => p.outbound_status !== 'shipped').length;
    const shippedCount = purchases.length - pendingCount;

    el.innerHTML = `
      <div class="toolbar reward-toolbar">
        <div class="row">
          <button data-action="reward-tab" data-tab="shop" class="${RewardPage.currentTab === 'shop' ? 'active-tab' : 'ghost'}">购买界面</button>
          <button data-action="reward-tab" data-tab="outbound" class="${RewardPage.currentTab === 'outbound' ? 'active-tab' : 'ghost'}">出库状态</button>
          <button class="ghost" data-action="refresh">刷新</button>
        </div>
        <span class="muted">
          奖励 ${rows.length} 项 · 待出库 ${pendingCount} 项 · 已出库 ${shippedCount} 项 · 历练点 ${Number(wallet.practice_points || 0).toFixed(1)} · 成长点 ${Number(wallet.growth_points || 0).toFixed(1)}
        </span>
      </div>

      ${RewardPage.currentTab === 'shop' ? `
        <div class="toolbar sub-toolbar">
          <button data-action="new-reward">新建奖励</button>
          <span class="muted">购买成功后会立即扣点和减库存，并进入“待出库”状态。</span>
        </div>
        <div class="grid cols reward-grid">
          ${decoratedRows.length ? decoratedRows.map(r => RewardPage.rewardCard(r, wallet)).join('') : UI.empty('暂无奖励')}
        </div>
      ` : `
        <div class="panel outbound-tip">
          <h3>待出库奖励</h3>
          <p class="muted">这里显示所有已经购买过的奖励。未出库的奖励可点击“确认出库”；已出库的卡片会变灰并自动排在末尾。</p>
        </div>
        <div class="grid cols reward-grid">
          ${sortedPurchases.length ? sortedPurchases.map(p => RewardPage.purchaseCard(p)).join('') : UI.empty('还没有购买记录')}
        </div>
      `}
    `;

    el.onclick = async (e) => {
      const target = e.target.closest('[data-action]');
      if (!target) return;

      const a = target.dataset.action;
      const id = target.dataset.id;

      if (a === 'reward-tab') {
        RewardPage.currentTab = target.dataset.tab || 'shop';
        return App.setPage('rewards');
      }

      if (a === 'new-reward') {
        return RewardPage.openForm();
      }

      if (a === 'refresh') {
        return App.setPage('rewards');
      }

      if (a === 'reward-buy') {
        await API.post(`/api/rewards/${id}/purchase`);
        UI.toast('兑换成功，奖励已进入待出库');
        await App.refreshWallet();
        RewardPage.currentTab = 'outbound';
        return App.setPage('rewards');
      }

      if (a === 'reward-outbound') {
        if (confirm('确认这个奖励已经兑现并出库？')) {
          await API.post(`/api/rewards/purchases/${id}/outbound`);
          UI.toast('奖励已出库');
          return App.setPage('rewards');
        }
      }

      if (a === 'reward-delete') {
        if (confirm('删除奖励会写入操作日志，确定删除？')) {
          await API.del(`/api/rewards/${id}`);
          UI.toast('已删除奖励');
          return App.setPage('rewards');
        }
      }
    };
  },

  sortGroup(r) {
    const stock = Number(r.stock || 0);

    if (stock <= 0 || r.display_status === '售空' || r.status === 'sold_out') {
      return 3;
    }

    if (r.affordable) {
      return 1;
    }

    return 2;
  },

  progressInfo(r, wallet) {
    const price = Number(r.price || 0);

    const balance = r.point_type === 'growth'
      ? Number(wallet.growth_points || 0)
      : Number(wallet.practice_points || 0);

    const rawPercent = price <= 0 ? 100 : (balance / price) * 100;
    const percent = Math.max(0, Math.min(100, rawPercent));
    const hue = Math.round(percent * 1.2);
    const barColor = `hsl(${hue}, 78%, 52%)`;

    return {
      price,
      balance,
      percent,
      hue,
      barColor,
      needMore: Math.max(price - balance, 0),
    };
  },

  rewardCard(r, wallet) {
    const info = RewardPage.progressInfo(r, wallet);

    const pointLabel = r.point_type === 'growth' ? '成长点' : '历练点';

    const statusClass =
      r.display_status === '售空' || Number(r.stock || 0) <= 0
        ? 'soldout'
        : r.affordable
          ? 'ok'
          : 'no';

    const progressText = statusClass === 'soldout'
      ? '该奖励已售空'
      : r.affordable
        ? '已满足兑换条件，购买后进入待出库'
        : `还差 ${info.needMore.toFixed(1)} ${pointLabel}`;

    return `
      <article class="card reward reward-card ${statusClass}">
        <div class="card-head">
          <div>
            <h3>${UI.esc(r.name)}</h3>
            <p class="muted">${UI.esc(r.content || '没有描述')}</p>
          </div>
          <span class="badge">${UI.esc(r.display_status)}</span>
        </div>

        <div class="reward-price-row">
          <span>价格</span>
          <strong>${info.price.toFixed(1)} ${pointLabel}</strong>
        </div>

        <div class="reward-price-row">
          <span>当前拥有</span>
          <strong>${info.balance.toFixed(1)} ${pointLabel}</strong>
        </div>

        <div class="reward-progress-wrap">
          <div class="reward-progress-top">
            <span>购买进度</span>
            <strong>${info.percent.toFixed(0)}%</strong>
          </div>

          <div class="reward-progress-track">
            <div
              class="reward-progress-fill"
              style="width: ${info.percent}%; background: ${info.barColor}; box-shadow: 0 0 16px ${info.barColor};"
            ></div>
          </div>

          <div class="reward-progress-note">
            ${UI.esc(progressText)}
          </div>
        </div>

        <div class="reward-stock-row">
          <span>库存</span>
          <strong>${Number(r.stock || 0)}</strong>
        </div>

        <div class="actions">
          <button
            data-action="reward-buy"
            data-id="${r.id}"
            ${!r.affordable ? 'disabled' : ''}
          >
            购买
          </button>

          <button
            class="danger ghost"
            data-action="reward-delete"
            data-id="${r.id}"
          >
            删除
          </button>
        </div>
      </article>
    `;
  },

  purchaseCard(p) {
    const shipped = p.outbound_status === 'shipped';
    const pointLabel = p.point_type === 'growth' ? '成长点' : '历练点';

    return `
      <article class="card reward reward-card purchase-card ${shipped ? 'shipped' : 'pending'}">
        <div class="card-head">
          <div>
            <h3>${UI.esc(p.display_name || p.reward_name || '已购买奖励')}</h3>
            <p class="muted">${UI.esc(p.display_content || p.reward_content || '没有描述')}</p>
          </div>
          <span class="badge ${shipped ? '' : 'gold'}">${UI.esc(p.outbound_status_label || (shipped ? '已出库' : '待出库'))}</span>
        </div>

        <div class="reward-price-row">
          <span>购买时间</span>
          <strong>${UI.esc(p.purchased_at || '-')}</strong>
        </div>

        <div class="reward-price-row">
          <span>消耗</span>
          <strong>${Number(p.price || 0).toFixed(1)} ${pointLabel}</strong>
        </div>

        <div class="reward-price-row">
          <span>购买后余额</span>
          <strong>${Number(p.balance_after || 0).toFixed(1)} ${pointLabel}</strong>
        </div>

        <div class="reward-stock-row">
          <span>购买后库存</span>
          <strong>${Number(p.stock_after || 0)}</strong>
        </div>

        ${shipped ? `
          <div class="outbound-seal">已出库</div>
          <p class="muted">出库时间：${UI.esc(p.outbound_at || '-')}</p>
        ` : `
          <div class="actions">
            <button data-action="reward-outbound" data-id="${p.id}">确认出库</button>
          </div>
        `}
      </article>
    `;
  },

  openForm(r = null) {
    UI.modal(
      r ? '编辑奖励' : '新建奖励',
      `
      <form id="reward-form" class="form">
        <label>
          名称
          <input name="name" value="${UI.esc(r?.name || '')}" required>
        </label>

        <label>
          内容
          <textarea name="content">${UI.esc(r?.content || '')}</textarea>
        </label>

        <label>
          点数类型
          <select name="point_type">
            <option value="practice" ${r?.point_type === 'practice' ? 'selected' : ''}>历练点</option>
            <option value="growth" ${r?.point_type === 'growth' ? 'selected' : ''}>成长点</option>
          </select>
        </label>

        <label>
          价格
          <input name="price" type="number" step="0.5" min="0" value="${r?.price || 1}">
        </label>

        <label>
          库存
          <input name="stock" type="number" min="0" value="${r?.stock ?? 1}">
        </label>
      </form>
      `,
      `
      <button id="save-reward">保存</button>
      `
    );

    document.getElementById('save-reward').onclick = async () => {
      const f = document.getElementById('reward-form');
      const data = UI.formData(f);

      data.price = Number(data.price);
      data.stock = Number(data.stock);

      await API.post('/api/rewards', data);

      UI.closeModal();
      UI.toast('奖励已保存');
      App.setPage('rewards');
    };
  },
};
