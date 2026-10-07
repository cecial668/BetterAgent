App.pages.today = { async load(){
  const data=await API.get('/api/quests/today'); await App.refreshWallet();
  const el=document.getElementById('page-today');
  el.innerHTML=`<div class="panel"><div class="between"><div><h3>${data.date} · ${data.is_vacation?'假期日':'普通日'}</h3><p class="muted">${UI.esc(data.condition.explain)}</p></div><div class="row"><button data-action="new-quest">新建委托</button><button class="ghost" data-action="manual">普通结算</button><button data-action="end">日终结算</button></div></div><div class="row"><span class="badge gold">${UI.esc(data.condition.day_title_preview)}</span><span class="badge">完成点数 ${Number(data.condition.total_points).toFixed(1)}</span><span class="badge">必要委托 ${data.condition.required_all_done?'已完成':'未完成'}</span></div></div><div class="grid">${data.quests.length?data.quests.map(q=>UI.questCard(q)).join(''):UI.empty('今天还没有委托。')}</div>`;
  el.onclick=async e=>{
    const a=e.target.dataset.action;
    if(a==='new-quest') return window.QuestPage.openForm();
    if(a==='manual'){ const r=await API.post('/api/settlements/manual',{}); UI.modal('普通结算结果', `<p>${UI.esc(r.explain)}</p><p>本次入池：<b>${Number(r.points_banked||0).toFixed(1)}</b> 点</p><p>当前余额：${Number(r.wallet.practice_points||0).toFixed(1)} 历练点</p>`); return App.setPage('today'); }
    if(a==='end'){ const r=await API.post('/api/settlements/end',{}); UI.modal('日终结算', `<p>${UI.esc(r.explain)}</p><p>完成委托：${UI.esc((r.completed_titles||[]).join('、')||'无')}</p><p>顺延委托：${UI.esc((r.carried_titles||[]).join('、')||'无')}</p>`); return App.setPage('today'); }
    if(a==='quest-complete'){ await API.post(`/api/quests/${e.target.dataset.id}/complete`,{completed:e.target.checked}); UI.toast('委托状态已更新'); return App.setPage('today'); }
  };
}};
