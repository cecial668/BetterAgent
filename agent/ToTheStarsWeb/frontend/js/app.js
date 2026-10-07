window.App = {
  state: {
    page: 'today',
    constants: {},
    bootstrap: null,
  },
  pages: {},
};

App.refreshWallet = async function () {
  const w = await API.get('/api/wallet');
  document.getElementById('wallet-bar').innerHTML = UI.wallet(w);
  return w;
};

App.setPage = async function (page) {
  App.state.page = page;

  document
    .querySelectorAll('#nav button')
    .forEach((b) => b.classList.toggle('active', b.dataset.page === page));

  document
    .querySelectorAll('.page')
    .forEach((p) => p.classList.remove('active'));

  const target = document.getElementById('page-' + page);
  target.classList.add('active');

  const title = document.querySelector(`#nav button[data-page="${page}"]`).textContent;
  document.getElementById('page-title').textContent = title;

  try {
    await App.pages[page]?.load?.();
  } catch (err) {
    target.innerHTML = `
      <div class="panel error-panel">
        <h3>页面加载失败</h3>
        <p>${UI.esc(err.message || err)}</p>
        <p class="muted">请确认后端正在运行，或打开浏览器开发者工具查看具体接口错误。</p>
      </div>
    `;
    UI.toast(err.message || '页面加载失败', 'error');
  }
};

App.showSettlementResults = function (title, results) {
  if (!results?.length) return;

  const body = `
    <div class="stack">
      ${results.map((r) => `
        <div class="panel">
          <h4>${UI.esc(r.date || '')} · ${UI.esc(r.day_title || '日终结算')}</h4>
          <p>新入池：${Number(r.points_banked || 0).toFixed(1)} 点；状态奖励：${Number(r.state_bonus || 0).toFixed(1)} 点。</p>
          <p class="muted">完成委托：${(r.completed_titles || []).map(UI.esc).join('、') || '无'}</p>
          <p class="muted">顺延委托：${(r.carried_titles || []).map(UI.esc).join('、') || '无'}</p>
          ${r.explain ? `<p class="muted">${UI.esc(r.explain)}</p>` : ''}
        </div>
      `).join('')}
    </div>
  `;

  UI.modal(title, body, '<button class="primary" data-close-modal>知道了</button>');

  const close = document.querySelector('#modal-root [data-close-modal]');
  if (close) {
    close.onclick = () => UI.closeModal();
  }
};

App.checkRollover = async function () {
  try {
    const data = await API.get('/api/rollover-status');

    if (data.wallet) {
      document.getElementById('wallet-bar').innerHTML = UI.wallet(data.wallet);
    }

    if (data.results?.length) {
      document.getElementById('sub-title').textContent =
        `今天是 ${data.date} · 数据库 ${App.state.bootstrap?.data_path || ''}`;

      App.showSettlementResults('凌晨 4 点日终结算完成', data.results);

      await App.setPage(App.state.page || 'today');
    }
  } catch (err) {
    console.warn('rollover check failed', err);
  }
};

App.startRolloverPolling = function () {
  if (App.state.rolloverTimer) {
    clearInterval(App.state.rolloverTimer);
  }

  // 每 30 秒询问一次后端：凌晨 4 点在线日终结算是否已经发生
  App.state.rolloverTimer = setInterval(App.checkRollover, 30000);
};

App.init = async function () {
  const boot = await API.get('/api/bootstrap');

  App.state.bootstrap = boot;
  App.state.constants = boot.constants;

  document.getElementById('sub-title').textContent =
    `今天是 ${boot.date} · 数据库 ${boot.data_path}`;

  document.getElementById('wallet-bar').innerHTML = UI.wallet(boot.wallet);

  if (boot.startup_results?.length) {
    const p = document.getElementById('startup-panel');
    p.classList.remove('hidden');

    p.innerHTML =
      '<h3>启动补结算摘要</h3>' +
      boot.startup_results
        .map((r) => `<p>${UI.esc(r.date)}：${UI.esc(r.day_title || '')}，入池 ${Number(r.points_banked || 0).toFixed(1)} 点</p>`)
        .join('');
  }

  document.getElementById('nav').onclick = (e) => {
    if (e.target.dataset.page) {
      App.setPage(e.target.dataset.page);
    }
  };

  document.getElementById('shutdown-btn').onclick = async () => {
    await API.post('/api/shutdown');
    UI.toast('已记录关闭时间，可以直接关闭窗口。');
  };

  await App.setPage('today');

  App.startRolloverPolling();
};

document.addEventListener('DOMContentLoaded', () =>
  App.init().catch((err) => {
    const page = document.getElementById('page-today');

    if (page) {
      page.innerHTML = `
        <div class="panel error-panel">
          <h3>启动失败</h3>
          <p>${UI.esc(err.message || err)}</p>
        </div>
      `;
    }

    UI?.toast?.(err.message || '启动失败', 'error');
  })
);