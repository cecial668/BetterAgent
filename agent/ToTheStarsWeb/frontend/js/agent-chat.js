/**
 * 向着星右下角的「和数字人说话」对话气泡（纯 DOM，无构建、无框架）。
 *
 * 链路：GET /api/agent/chat-config 拿连接参数（缺省关闭）→ 连 BetterAgent
 * WebGateway（ws://127.0.0.1:8080/ws?token=...&chat_id=...）。
 *   · 发送 {type:'user.text', payload:{text}}
 *   · 接收 agent.text_delta / agent.state_change / agent.tool_activity
 * 渲染为气泡、状态行与工具提示行；二进制音频帧直接忽略（气泡不做语音）。
 *
 * 隐私与安全：token 只从本机 8765 接口读取；所有模型输出一律用 textContent
 * 写入（绝不 innerHTML），即使模型输出带标签也不会被当成 DOM 执行。
 */
(function () {
  'use strict';

  const MAX_LOG_ITEMS = 200;
  const RECONNECT_BASE_MS = 1500;
  const RECONNECT_MAX_MS = 15000;
  const MAX_INPUT_LENGTH = 500;

  const state = {
    config: null,
    ws: null,
    opened: false,
    reconnectTimer: null,
    reconnectDelay: RECONNECT_BASE_MS,
    unread: 0,
    currentBubble: null,
    proposal: null,
    proposalDetails: false,
  };

  const els = {};

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function buildDom() {
    const root = el('div', 'agent-chat');
    root.id = 'agent-chat';

    const toggle = el('button', 'agent-chat-toggle');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', '和数字人说话');
    toggle.title = '和数字人说话';
    toggle.appendChild(el('span', 'agent-chat-toggle-icon', '✦'));
    const badge = el('span', 'agent-chat-badge', '0');
    badge.hidden = true;
    toggle.appendChild(badge);
    toggle.addEventListener('click', () => setOpened(!state.opened));

    const panel = el('section', 'agent-chat-panel');
    panel.hidden = true;
    panel.setAttribute('aria-label', '数字人对话');

    const head = el('header', 'agent-chat-head');
    const title = el('div', 'agent-chat-title');
    title.appendChild(el('span', 'agent-chat-title-dot'));
    const titleText = el('div', 'agent-chat-title-text');
    titleText.appendChild(el('b', null, '和数字人说话'));
    const status = el('small', 'agent-chat-status', '未连接');
    titleText.appendChild(status);
    title.appendChild(titleText);
    const close = el('button', 'agent-chat-close', '✕');
    close.type = 'button';
    close.setAttribute('aria-label', '收起对话');
    close.title = '收起对话';
    close.addEventListener('click', () => setOpened(false));
    head.appendChild(title);
    head.appendChild(close);

    const log = el('div', 'agent-chat-log');
    log.setAttribute('aria-live', 'polite');

    const proposal = el('div', 'agent-chat-proposal');
    proposal.hidden = true;

    const toolLine = el('div', 'agent-chat-tool');
    toolLine.hidden = true;

    const form = el('form', 'agent-chat-form');
    const input = el('input', 'agent-chat-input');
    input.type = 'text';
    input.maxLength = MAX_INPUT_LENGTH;
    input.placeholder = '说点什么…';
    input.autocomplete = 'off';
    const send = el('button', 'agent-chat-send', '发送');
    send.type = 'submit';
    form.appendChild(input);
    form.appendChild(send);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      sendText(input.value);
    });

    panel.appendChild(head);
    panel.appendChild(log);
    panel.appendChild(proposal);
    panel.appendChild(toolLine);
    panel.appendChild(form);
    root.appendChild(toggle);
    root.appendChild(panel);
    document.body.appendChild(root);

    els.toggle = toggle;
    els.badge = badge;
    els.panel = panel;
    els.status = status;
    els.log = log;
    els.toolLine = toolLine;
    els.input = input;
    els.proposal = proposal;
  }

  function setStatus(text, tone) {
    if (!els.status) return;
    els.status.textContent = text;
    els.status.dataset.tone = tone || '';
  }

  function setOpened(opened) {
    state.opened = opened;
    els.panel.hidden = !opened;
    els.toggle.classList.toggle('is-open', opened);
    if (opened) {
      state.unread = 0;
      updateBadge();
      scrollLog();
      els.input.focus();
      ensureSocket();
    }
  }

  function updateBadge() {
    if (!els.badge) return;
    els.badge.hidden = state.unread <= 0;
    els.badge.textContent = state.unread > 9 ? '9+' : String(state.unread);
  }

  function scrollLog() {
    if (els.log) els.log.scrollTop = els.log.scrollHeight;
  }

  function trimLog() {
    while (els.log.childNodes.length > MAX_LOG_ITEMS) els.log.removeChild(els.log.firstChild);
  }

  function notifyUnread() {
    if (!state.opened) {
      state.unread += 1;
      updateBadge();
    }
  }

  function appendMessage(role, text) {
    const wrap = el('div', `agent-chat-msg ${role}`);
    wrap.appendChild(el('div', 'agent-chat-bubble', text));
    els.log.appendChild(wrap);
    trimLog();
    scrollLog();
    return wrap;
  }

  function appendSystem(text) {
    els.log.appendChild(el('div', 'agent-chat-system', text));
    trimLog();
    scrollLog();
  }

  function appendDelta(text) {
    if (!text) return;
    if (!state.currentBubble) {
      state.currentBubble = appendMessage('assistant', '');
      notifyUnread();
    }
    state.currentBubble.firstChild.textContent += text;
    scrollLog();
  }

  function showTool(label) {
    els.toolLine.hidden = false;
    els.toolLine.textContent = label || '正在处理…';
  }

  function hideTool() {
    els.toolLine.hidden = true;
    els.toolLine.textContent = '';
  }

  // ---------- 写入确认框（agent.life_proposal） ----------

  const KIND_LABELS = {
    'commission.create': '新增每日委托',
    'commission.complete': '更新委托完成状态',
    'commission.update': '修改每日委托',
    'schedule.add': '新增日程计划',
    'audit.undo': '撤销上一步操作',
  };

  const PROPOSAL_FIELDS = {
    'commission.create': [
      { key: 'title', label: '标题', type: 'text' },
      { key: 'difficulty', label: '难度', type: 'select', options: ['A', 'B', 'C', 'D'] },
      { key: 'assigned_date', label: '日期（留空=今天）', type: 'date' },
      { key: 'description', label: '说明', type: 'textarea' },
      { key: 'category', label: '分类', type: 'text' },
      { key: 'is_required', label: '必要委托', type: 'checkbox' },
      { key: 'is_recurring', label: '日常重复', type: 'checkbox' },
    ],
    'commission.complete': [
      { key: 'completed', label: '标记为已完成（取消勾选=恢复未完成）', type: 'checkbox' },
    ],
    'commission.update': [
      { key: 'title', label: '标题', type: 'text' },
      { key: 'difficulty', label: '难度', type: 'select', options: ['A', 'B', 'C', 'D'] },
      { key: 'description', label: '说明', type: 'textarea' },
      { key: 'category', label: '分类', type: 'text' },
      { key: 'is_required', label: '必要委托', type: 'checkbox' },
      { key: 'is_recurring', label: '日常重复', type: 'checkbox' },
    ],
    'schedule.add': [
      { key: 'title', label: '标题', type: 'text' },
      { key: 'start', label: '开始（HH:MM）', type: 'text' },
      { key: 'end', label: '结束（HH:MM）', type: 'text' },
      { key: 'plan_date', label: '日期（留空=今天）', type: 'date' },
      { key: 'content', label: '备注', type: 'textarea' },
    ],
    'audit.undo': [],
  };

  function proposalSourceParams(p) {
    if (p.kind === 'commission.update' && p.params && p.params.body) return p.params.body;
    return p.params || {};
  }

  function updateProposalBox() {
    const box = els.proposal;
    if (!box) return;
    const p = state.proposal;
    if (!p) {
      box.hidden = true;
      box.textContent = '';
      return;
    }

    const terminal = ['executed', 'failed', 'cancelled', 'expired'].indexOf(p.phase) !== -1;
    box.hidden = false;
    box.dataset.phase = p.phase;
    box.textContent = '';

    const head = el('div', 'agent-chat-proposal-head');
    head.appendChild(el('span', 'agent-chat-proposal-title', '需要确认'));
    head.appendChild(el('span', 'agent-chat-proposal-kind', KIND_LABELS[p.kind] || p.kind || '修改'));
    box.appendChild(head);
    box.appendChild(el('div', 'agent-chat-proposal-summary', p.summary || ''));

    if (terminal) {
      const note = p.phase === 'failed'
        ? '写入失败：' + (p.message || '未知原因')
        : p.phase === 'cancelled'
          ? '已取消，没有产生任何修改'
          : p.phase === 'expired'
            ? '提议已失效'
            : '已执行：' + (p.message || '完成');
      box.appendChild(el('div', 'agent-chat-proposal-result ' + (p.phase === 'failed' ? 'is-error' : 'is-ok'), note));
      return;
    }

    const specs = PROPOSAL_FIELDS[p.kind] || [];
    if (specs.length) {
      const toggle = el('button', 'agent-chat-proposal-toggle', state.proposalDetails ? '收起详情' : '查看详情 / 手动修改');
      toggle.type = 'button';
      toggle.addEventListener('click', () => {
        state.proposalDetails = !state.proposalDetails;
        updateProposalBox();
      });
      box.appendChild(toggle);

      if (state.proposalDetails) {
        const form = el('div', 'agent-chat-proposal-form');
        const source = proposalSourceParams(p);
        specs.forEach((spec) => {
          const row = el('label', 'agent-chat-proposal-field');
          row.appendChild(el('span', 'agent-chat-proposal-label', spec.label));
          let input;
          if (spec.type === 'textarea') {
            input = el('textarea');
            input.rows = 2;
          }
          else if (spec.type === 'select') {
            input = el('select');
            spec.options.forEach((value) => {
              const option = el('option', null, value);
              option.value = value;
              input.appendChild(option);
            });
          }
          else {
            input = el('input');
            input.type = spec.type;
          }
          const current = source[spec.key];
          if (spec.type === 'checkbox') input.checked = !!current;
          else input.value = current == null ? '' : String(current);
          input.dataset.key = spec.key;
          input.dataset.type = spec.type;
          row.appendChild(input);
          form.appendChild(row);
        });
        box.appendChild(form);
      }
    }

    const actions = el('div', 'agent-chat-proposal-actions');
    const cancelBtn = el('button', 'agent-chat-proposal-btn cancel', '取消');
    cancelBtn.type = 'button';
    cancelBtn.disabled = p.phase === 'executing';
    cancelBtn.addEventListener('click', () => sendProposalDecision('cancel'));
    const confirmBtn = el('button', 'agent-chat-proposal-btn confirm', p.phase === 'executing' ? '正在执行…' : '确认执行');
    confirmBtn.type = 'button';
    confirmBtn.disabled = p.phase === 'executing';
    confirmBtn.addEventListener('click', () => sendProposalDecision('confirm'));
    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    box.appendChild(actions);
  }

  function collectProposalEdits() {
    const edits = {};
    if (!els.proposal) return edits;
    els.proposal.querySelectorAll('input[data-key], textarea[data-key], select[data-key]').forEach((node) => {
      const type = node.dataset.type;
      edits[node.dataset.key] = type === 'checkbox' ? !!node.checked : node.value;
    });
    return edits;
  }

  function sendProposalDecision(action) {
    const p = state.proposal;
    if (!p) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      appendSystem('还没连上数字人，无法发送确认');
      return;
    }
    const edits = action === 'confirm' ? collectProposalEdits() : {};
    const sentinel = '【确认框】' + JSON.stringify({ v: 1, id: p.proposal_id, action: action, edits: edits });
    // 哨兵走普通 user.text：确认后的执行与语言反馈复用完整对话管线，
    // 且这里不往聊天记录里加用户气泡（机器消息不出现在界面上）。
    state.ws.send(JSON.stringify({ type: 'user.text', payload: { text: sentinel } }));
    p.phase = 'executing';
    state.proposalDetails = false;
    updateProposalBox();
    appendSystem(action === 'confirm' ? '已确认，正在执行…' : '已取消这次修改');
  }

  function handleLifeProposal(payload) {
    if (!payload || !payload.proposal_id) return;

    // 只处理自己这条会话的提议：Go 会把带 chat_id 的帧广播给所有会话，
    // 舞台那边发起的提议不该在向着星气泡里弹框（反之亦然）。
    const WEB_NAMESPACE_OFFSET = 9000000000000000;
    if (payload.chat_id != null && state.config && state.config.chat_id) {
      const mine = Number(state.config.chat_id);
      const folded = Number(payload.chat_id);
      if (Number.isFinite(mine) && Number.isFinite(folded) && folded !== WEB_NAMESPACE_OFFSET + mine)
        return;
    }

    if (payload.phase === 'pending') {
      state.proposal = payload;
      state.proposalDetails = false;
      updateProposalBox();
      if (!state.opened) setOpened(true);
      notifyUnread();
      return;
    }

    if (!state.proposal || payload.proposal_id !== state.proposal.proposal_id) return;
    state.proposal = payload;
    updateProposalBox();

    if (payload.phase !== 'executing') {
      const id = payload.proposal_id;
      setTimeout(() => {
        if (state.proposal && state.proposal.proposal_id === id) {
          state.proposal = null;
          updateProposalBox();
        }
      }, 2600);
    }
  }

  const STATE_TEXT = {
    THINKING: ['思考中…', 'busy'],
    TALKING: ['说话中…', 'busy'],
    SLEEPING: ['休息中', 'idle'],
    IDLE: ['在线', 'online'],
  };

  function handleFrame(frame) {
    if (!frame || typeof frame.type !== 'string') return;
    const payload = frame.payload || {};
    if (frame.type === 'agent.text_delta') {
      appendDelta(payload.text || '');
      if (payload.is_final) state.currentBubble = null;
      return;
    }
    if (frame.type === 'agent.state_change') {
      const info = STATE_TEXT[payload.state] || [payload.state || '在线', 'online'];
      setStatus(info[0], info[1]);
      if (payload.state === 'IDLE') state.currentBubble = null;
      return;
    }
    if (frame.type === 'agent.tool_activity') {
      if (payload.phase === 'start') showTool(payload.label);
      else hideTool();
      return;
    }
    if (frame.type === 'agent.life_proposal') {
      handleLifeProposal(payload);
    }
  }

  function ensureSocket() {
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) return;
    if (!state.config || !state.config.enabled) return;
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }

    const { ws_url, token, chat_id } = state.config;
    const url = `${ws_url}?token=${encodeURIComponent(token)}&chat_id=${encodeURIComponent(chat_id)}`;
    setStatus('连接中…', 'busy');

    let socket;
    try {
      socket = new WebSocket(url);
    } catch (err) {
      scheduleReconnect();
      return;
    }
    state.ws = socket;

    socket.addEventListener('open', () => {
      state.reconnectDelay = RECONNECT_BASE_MS;
      setStatus('在线', 'online');
    });
    socket.addEventListener('message', (event) => {
      if (typeof event.data !== 'string') return; // 二进制音频帧：气泡不处理
      try {
        handleFrame(JSON.parse(event.data));
      } catch (err) {
        /* 坏帧忽略，不影响后续消息 */
      }
    });
    socket.addEventListener('close', () => {
      state.ws = null;
      state.currentBubble = null;
      hideTool();
      if (state.opened) setStatus('离线，正在重连…', 'offline');
      scheduleReconnect();
    });
    socket.addEventListener('error', () => {
      /* close 事件会随后触发，统一在那里处理重连 */
    });
  }

  function scheduleReconnect() {
    if (state.reconnectTimer) return;
    state.reconnectTimer = setTimeout(() => {
      state.reconnectTimer = null;
      ensureSocket();
    }, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 1.6, RECONNECT_MAX_MS);
  }

  function sendText(raw) {
    const text = String(raw || '').trim();
    if (!text) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      appendSystem('还没连上数字人，正在重连…');
      ensureSocket();
      return;
    }
    appendMessage('user', text);
    state.currentBubble = null;
    state.ws.send(JSON.stringify({ type: 'user.text', payload: { text } }));
    els.input.value = '';
    els.input.focus();
  }

  async function init() {
    try {
      const res = await fetch('/api/agent/chat-config', { headers: { Accept: 'application/json' } });
      if (!res.ok) return;
      const config = await res.json();
      if (!config || !config.enabled) return; // 缺省关闭：不渲染任何东西
      state.config = config;
      buildDom();
      ensureSocket();
    } catch (err) {
      // 后台不可达：静默不渲染，避免留下一个永远连不上的按钮
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
