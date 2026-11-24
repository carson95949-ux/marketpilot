(()=>{
  const navs=[...document.querySelectorAll('[data-tab-group]')];
  if(!navs.length)return;

  function activate(group,target,updateHash=true){
    const nav=document.querySelector(`[data-tab-group="${group}"]`);
    if(!nav)return;
    nav.querySelectorAll('[data-tab-target]').forEach(btn=>{
      const on=btn.dataset.tabTarget===target;
      btn.classList.toggle('active',on);
      btn.setAttribute('aria-selected',on?'true':'false');
    });
    document.querySelectorAll('[data-tab-pane]').forEach(pane=>{
      if(pane.closest('.tool-shell') && group!=='tool') return;
      if(pane.closest('.account-page') && group!=='account') return;
      pane.classList.toggle('active',pane.dataset.tabPane===target);
    });
    try{localStorage.setItem(`marketpilot_tab_${group}`,target)}catch(_e){}
    if(updateHash && group==='account') history.replaceState(null,'','#'+target);
  }

  navs.forEach(nav=>{
    const group=nav.dataset.tabGroup;
    nav.querySelectorAll('[data-tab-target]').forEach(btn=>btn.addEventListener('click',()=>activate(group,btn.dataset.tabTarget,true)));
    let initial='';
    const hash=location.hash.replace('#','');
    if(group==='account' && hash && nav.querySelector(`[data-tab-target="${hash}"]`)) initial=hash;
    if(!initial){try{initial=localStorage.getItem(`marketpilot_tab_${group}`)||''}catch(_e){}}
    if(!initial || !nav.querySelector(`[data-tab-target="${initial}"]`)) initial=nav.querySelector('[data-tab-target].active')?.dataset.tabTarget || nav.querySelector('[data-tab-target]')?.dataset.tabTarget;
    if(initial) activate(group,initial,false);
  });

  document.querySelectorAll('[data-open-tab]').forEach(btn=>btn.addEventListener('click',()=>{
    const target=btn.dataset.openTab;
    const group=btn.closest('.account-page')?'account':'tool';
    activate(group,target,true);
    window.scrollTo({top:0,behavior:'smooth'});
  }));

  window.addEventListener('hashchange',()=>{
    const target=location.hash.replace('#','');
    const nav=document.querySelector('[data-tab-group="account"]');
    if(target && nav?.querySelector(`[data-tab-target="${target}"]`)) activate('account',target,false);
  });
})();
