(() => {
  const root = document.getElementById('toolRoot');
  if (!root || root.dataset.initialized === '1') return;
  root.dataset.initialized = '1';

  const $ = (id) => document.getElementById(id);
  const state = { marketId: null, deadline: 0, target: null, initialSeconds: 300, btc: null, points: [], lastPointAt: 0, tradeStatus: new Map(), firstTradeSync: true, soundOn: localStorage.getItem('marketpilot_sound') === 'on', lastTargetRelation: null, lastCrossSoundAt: 0, fastPollUntil: 0, deadlineFastArmed: false, polling: false };
  const money = (v) => Number.isFinite(Number(v)) ? '$' + Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
  const cents = (v) => Number.isFinite(Number(v)) ? Math.round(Number(v)*100) + '¢' : '—';
  const pct = (v) => Number.isFinite(Number(v)) ? (Number(v)*100).toFixed(1) + '%' : '—';
  const signed = (v) => Number.isFinite(Number(v)) ? (Number(v)>=0?'+':'') + Number(v).toFixed(2) : '—';
  const setText = (id, text) => { const el=$(id); if(el && el.textContent!==String(text)) el.textContent=String(text); };

  function setClass(el, base, variant){ if(!el)return; el.className=base + (variant ? ' ' + variant : ''); }

  function updateSoundButton(){
    const b=$('soundToggle'); if(!b)return;
    b.textContent=state.soundOn?'Sound: On':'Sound: Off';
    b.setAttribute('aria-pressed',state.soundOn?'true':'false');
    b.classList.toggle('on',state.soundOn);
  }

  function playWinChime(){
    if(!state.soundOn) return;
    try{
      const AC=window.AudioContext||window.webkitAudioContext; if(!AC)return;
      const ac=new AC(), now=ac.currentTime;
      // Cash-register style "cha-ching": short drawer click + bright metallic double chime.
      const click=ac.createBuffer(1,Math.floor(ac.sampleRate*.055),ac.sampleRate);
      const data=click.getChannelData(0);
      for(let i=0;i<data.length;i++) data[i]=(Math.random()*2-1)*Math.exp(-i/(ac.sampleRate*.012));
      const src=ac.createBufferSource(), cg=ac.createGain(); src.buffer=click; cg.gain.value=.13; src.connect(cg); cg.connect(ac.destination); src.start(now);
      [1046.5,1568.0,1318.5].forEach((freq,i)=>{
        const o=ac.createOscillator(), g=ac.createGain();
        o.type=i===1?'triangle':'sine'; o.frequency.value=freq;
        const t=now+.07+i*.09;
        g.gain.setValueAtTime(.0001,t); g.gain.exponentialRampToValueAtTime(i===1?.15:.11,t+.012); g.gain.exponentialRampToValueAtTime(.0001,t+.30);
        o.connect(g); g.connect(ac.destination); o.start(t); o.stop(t+.32);
      });
      setTimeout(()=>ac.close().catch(()=>{}),850);
      const track=document.querySelector('.stats-grid'); if(track){track.classList.remove('win-flash'); void track.offsetWidth; track.classList.add('win-flash');}
    }catch(_e){}
  }

  function playSoundEnabled(){
    if(!state.soundOn)return;
    try{const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;const ac=new AC(),o=ac.createOscillator(),g=ac.createGain(),t=ac.currentTime;o.type='sine';o.frequency.value=660;g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.06,t+.01);g.gain.exponentialRampToValueAtTime(.0001,t+.09);o.connect(g);g.connect(ac.destination);o.start(t);o.stop(t+.1);setTimeout(()=>ac.close().catch(()=>{}),220)}catch(_e){}
  }

  function playTargetCross(direction){
    if(!state.soundOn || Date.now()-state.lastCrossSoundAt<8000) return;
    state.lastCrossSoundAt=Date.now();
    try{
      const AC=window.AudioContext||window.webkitAudioContext; if(!AC)return;
      const ac=new AC(),now=ac.currentTime;
      const notes=direction==='above'?[523.25,659.25]:[523.25,392.0];
      notes.forEach((freq,i)=>{const o=ac.createOscillator(),g=ac.createGain();o.type='triangle';o.frequency.value=freq;g.gain.setValueAtTime(.0001,now+i*.08);g.gain.exponentialRampToValueAtTime(.08,now+i*.08+.015);g.gain.exponentialRampToValueAtTime(.0001,now+i*.08+.16);o.connect(g);g.connect(ac.destination);o.start(now+i*.08);o.stop(now+i*.08+.18)});
      setTimeout(()=>ac.close().catch(()=>{}),450);
    }catch(_e){}
  }

  function showCrossToast(direction){
    const el=$('crossToast'); if(!el)return;
    el.textContent=direction==='above'?'BTC crossed ABOVE price to beat':'BTC crossed BELOW price to beat';
    el.className='cross-toast show '+direction;
    clearTimeout(showCrossToast._t); showCrossToast._t=setTimeout(()=>{el.className='cross-toast'},2400);
  }

  function updateBankrollPlan(){
    const input=$('bankrollInput'); if(!input)return;
    let b=Number(input.value); if(!Number.isFinite(b))b=1000; b=Math.max(25,Math.min(1000000,b));
    const riskPct=.01, dailyPct=.05, openPct=.02, reservePct=.80;
    setText('planRisk',money(Math.max(1,b*riskPct)));
    setText('planStop',money(Math.max(5,b*dailyPct)));
    setText('planOpen',money(Math.max(1,b*openPct)));
    setText('planReserve',money(b*reservePct));
  }

  function updateAccess(a){
    if(!a) return;
    if(a.kind === 'purchase') setText('accessBadge','UNLOCKED');
    else {
      const sec=Math.max(0,Number(a.remaining_seconds||0));
      const m=Math.floor(sec/60), s=Math.floor(sec%60);
      setText('accessBadge',`TRIAL ${m}:${String(s).padStart(2,'0')}`);
    }
  }

  function updateMarket(data){
    if(!data.ready) return;
    const m=data.market, st=data.stats||{};
    const incomingMarketId=String(m.market_id||'');
    const newRound=Boolean(incomingMarketId && incomingMarketId!==state.marketId);
    if(newRound){
      // Clear all round-specific display state before applying the new round.
      // This prevents the prior Price To Beat from flashing into the next market.
      state.marketId=incomingMarketId;
      state.target=null; state.lastTargetRelation=null;
      state.deadline=0; state.deadlineFastArmed=false; state.fastPollUntil=0;
      setText('targetPrice','—');
      drawChart();
    }
    state.deadline=Number(m.deadline_ms||0);
    state.target=Number.isFinite(Number(m.target))?Number(m.target):null;
    const remaining=Math.max(0,Math.ceil((state.deadline-Date.now())/1000));
    if(newRound || !state.initialSeconds) state.initialSeconds=Math.max(1,remaining);

    const decision=$('decisionState');
    setText('decisionState',m.state); setClass(decision,'decision-state',m.state_kind||'wait');
    setText('decisionReason',m.reason||''); setText('decisionBadge',m.badge||'SCANNING'); setText('sessionLabel',m.session_label||'—');
    $('confirmFill').style.width=(Number(m.confirmation_progress||0))+'%';
    setText('confirmText',`${m.confirmation_count||0} / ${m.confirmation_required||3} confirmations`);
    setText('targetPrice',money(m.target)); setText('upPrice',cents(m.yes_ask)); setText('downPrice',cents(m.no_ask));
    setText('entryTitle',`${m.lean_side} entry zone`); setText('entrySideLabel',`${m.lean_side} MAX BUY PRICE`); setText('maxBuy',cents(m.max_buy));
    setText('entryStatus',`${m.entry_available?'ENTRY AVAILABLE':'WAIT FOR PRICE'} · current ${m.lean_side} ${cents(m.ask)}`);
    setText('fairProb',pct(m.fair)); setText('edgeValue',pct(m.edge)); setText('chartRead',m.chart_read||'—'); setText('bookPressure',signed(m.book_imbalance));
    setText('paperPnl',money(st.pnl)); setText('winRate',st.settled?pct(st.win_rate):'—'); setText('winStreak',st.current_streak??'—'); setText('settledTrades',st.settled??'—'); setText('tradeFrequency',st.rounds_observed?pct(st.trade_frequency):'—'); setText('roundsObserved',`${st.rounds_observed??0} rounds observed`);
    renderTrades(data.trades||[]); updateAccess(data.access); drawChart();
  }

  function renderTrades(rows){
    const body=$('tradeRows'); if(!body)return;
    if(!rows.length){ body.innerHTML='<tr><td colspan="7" class="muted">No trades yet.</td></tr>'; state.firstTradeSync=false; return; }
    for(const r of rows){
      const key=String(r.id ?? r.opened_ts ?? '');
      const prev=state.tradeStatus.get(key);
      const nowStatus=String(r.status||'').toUpperCase();
      const pnl=Number(r.pnl);
      if(!state.firstTradeSync && prev && prev!=='SETTLED' && nowStatus==='SETTLED' && Number.isFinite(pnl) && pnl>0) playWinChime();
      state.tradeStatus.set(key,nowStatus);
    }
    state.firstTradeSync=false;
    body.innerHTML=rows.map(r=>{
      const pnl=Number(r.pnl); const pcls=Number.isFinite(pnl)?(pnl>0?'positive':pnl<0?'negative':''):'';
      const when=r.opened_ts?new Date(r.opened_ts).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—';
      return `<tr><td>${when}</td><td>${r.side||'—'}</td><td>${cents(r.entry_price)}</td><td>${pct(r.model_probability)}</td><td>${pct(r.net_edge)}</td><td>${r.status||'—'}</td><td class="${pcls}">${Number.isFinite(pnl)?money(pnl):'—'}</td></tr>`;
    }).join('');
  }

  async function pollState(){
    if(state.polling) return;
    state.polling=true;
    try{
      const res=await fetch('/api/state',{cache:'no-store'});
      const data=await res.json();
      if(res.status===403){ window.location.href=data.redirect||'/purchase'; return; }
      if(data.ok) updateMarket(data);
    }catch(e){ /* keep existing UI; retry next poll */ }
    finally{ state.polling=false; }
  }

  function tickTimers(){
    if(state.deadline){
      const sec=Math.max(0,Math.ceil((state.deadline-Date.now())/1000));
      setText('marketTimer',`${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`);
      const width=Math.max(0,Math.min(100,100*sec/Math.max(1,state.initialSeconds)));
      $('timerFill').style.width=width+'%';
      if(!state.deadlineFastArmed && sec<=5){
        state.deadlineFastArmed=true;
        state.fastPollUntil=state.deadline+20000;
      }
    }
    const badge=$('accessBadge');
    if(badge && badge.textContent.startsWith('TRIAL ')){
      // Server polling corrects this every 2s; this just makes it tick smoothly between polls.
      const m=badge.textContent.match(/TRIAL (\d+):(\d+)/);
      if(m){ let sec=Number(m[1])*60+Number(m[2]); sec=Math.max(0,sec-1); badge.textContent=`TRIAL ${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`; }
    }
  }

  async function seedHistory(){
    try{
      const res=await fetch('/api/btc-history',{cache:'no-store'}); const data=await res.json();
      if(data.ok && Array.isArray(data.points)){ state.points=data.points; if(state.points.length){state.btc=state.points[state.points.length-1].p; setText('btcLive',money(state.btc)); setText('chartPrice','BTC '+money(state.btc));} drawChart(); }
    }catch(e){}
  }

  const wrap=$('chartWrap'), canvas=$('btcChart'), ctx=canvas.getContext('2d');
  function resize(){ const dpr=window.devicePixelRatio||1,r=wrap.getBoundingClientRect(); canvas.width=Math.max(1,r.width*dpr); canvas.height=Math.max(1,r.height*dpr); ctx.setTransform(dpr,0,0,dpr,0,0); drawChart(); }
  if('ResizeObserver' in window) new ResizeObserver(resize).observe(wrap); else window.addEventListener('resize',resize);

  function addPoint(t,p){
    if(!Number.isFinite(p))return;
    if(t-state.lastPointAt<250 && state.points.length) state.points[state.points.length-1]={t,p};
    else {state.points.push({t,p}); state.lastPointAt=t;}
    const cutoff=Date.now()-30*60*1000; while(state.points.length>2 && state.points[0].t<cutoff) state.points.shift();
    state.btc=p; setText('btcLive',money(p)); setText('chartPrice','BTC '+money(p));
    if(Number.isFinite(state.target)){
      const rel=p>=state.target?'above':'below';
      if(state.lastTargetRelation && rel!==state.lastTargetRelation){ playTargetCross(rel); showCrossToast(rel); }
      state.lastTargetRelation=rel;
    }
    drawChart();
  }

  function drawChart(){
    const W=wrap.clientWidth,H=wrap.clientHeight; if(!W||state.points.length<2)return;
    ctx.clearRect(0,0,W,H); const L=14,R=74,T=44,B=24,horizon=30*60*1000,minT=Date.now()-horizon;
    const v=state.points.filter(x=>x.t>=minT); if(v.length<2)return;
    const vals=v.map(x=>x.p); if(Number.isFinite(state.target)) vals.push(state.target);
    let lo=Math.min(...vals),hi=Math.max(...vals),pad=Math.max((hi-lo)*.14,hi*.0002); lo-=pad; hi+=pad;
    const X=t=>L+(t-minT)/horizon*(W-L-R),Y=p=>T+(hi-p)/(hi-lo)*(H-T-B);
    ctx.strokeStyle='#18221b';ctx.fillStyle='#6e7b73';ctx.font='10px Inter';
    for(let i=0;i<5;i++){let y=T+(H-T-B)*i/4;ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-R+8,y);ctx.stroke();ctx.fillText('$'+Math.round(hi-(hi-lo)*i/4).toLocaleString(),W-R+12,y+3)}
    if(Number.isFinite(state.target)){let y=Y(state.target);ctx.save();ctx.setLineDash([6,5]);ctx.strokeStyle='#f3c765';ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-R+8,y);ctx.stroke();ctx.restore();ctx.fillStyle='#f3c765';ctx.fillText('PRICE TO BEAT',L+5,Math.max(T+11,y-7));}
    const g=ctx.createLinearGradient(0,T,0,H-B);g.addColorStop(0,'rgba(125,242,127,.16)');g.addColorStop(1,'rgba(125,242,127,0)');
    ctx.beginPath();v.forEach((q,i)=>i?ctx.lineTo(X(q.t),Y(q.p)):ctx.moveTo(X(q.t),Y(q.p)));ctx.lineTo(X(v[v.length-1].t),H-B);ctx.lineTo(X(v[0].t),H-B);ctx.closePath();ctx.fillStyle=g;ctx.fill();
    ctx.beginPath();v.forEach((q,i)=>i?ctx.lineTo(X(q.t),Y(q.p)):ctx.moveTo(X(q.t),Y(q.p)));ctx.strokeStyle='#7df27f';ctx.lineWidth=2.1;ctx.stroke();
  }

  function connectWs(){
    const label=$('wsStatus'); let ws;
    try{ ws=new WebSocket('wss://ws-feed.exchange.coinbase.com'); }catch(e){ setTimeout(connectWs,1500); return; }
    ws.onopen=()=>{ label.textContent='● LIVE BTC-USD'; label.classList.add('live'); ws.send(JSON.stringify({type:'subscribe',product_ids:['BTC-USD'],channels:['ticker']})); };
    ws.onmessage=e=>{ try{const m=JSON.parse(e.data);if(m.type==='ticker'&&m.price)addPoint(Date.parse(m.time)||Date.now(),Number(m.price));}catch(_e){} };
    ws.onclose=()=>{ label.textContent='RECONNECTING'; label.classList.remove('live'); setTimeout(connectWs,1200); };
    ws.onerror=()=>{ try{ws.close();}catch(_e){} };
  }

  const soundBtn=$('soundToggle');
  if(soundBtn){ soundBtn.addEventListener('click',()=>{ state.soundOn=!state.soundOn; localStorage.setItem('marketpilot_sound',state.soundOn?'on':'off'); updateSoundButton(); if(state.soundOn) playSoundEnabled(); }); }
  const bankrollInput=$('bankrollInput'); if(bankrollInput){ bankrollInput.addEventListener('input',updateBankrollPlan); updateBankrollPlan(); }
  const helpDrawer=$('helpDrawer'),helpBackdrop=$('helpBackdrop'),helpAnswer=$('helpAnswer');
  function openHelp(){if(!helpDrawer)return;helpDrawer.classList.add('open');helpDrawer.setAttribute('aria-hidden','false');if(helpBackdrop)helpBackdrop.hidden=false;}
  function closeHelp(){if(!helpDrawer)return;helpDrawer.classList.remove('open');helpDrawer.setAttribute('aria-hidden','true');if(helpBackdrop)helpBackdrop.hidden=true;}
  $('helpOpen')?.addEventListener('click',openHelp); $('helpFloat')?.addEventListener('click',openHelp); $('helpClose')?.addEventListener('click',closeHelp); helpBackdrop?.addEventListener('click',closeHelp);
  document.querySelectorAll('[data-help-q]').forEach(b=>b.addEventListener('click',()=>askHelp(b.dataset.helpQ||'')));
  async function askHelp(q){
    q=String(q||'').trim(); if(!q)return;
    if(helpAnswer)helpAnswer.textContent='Thinking…';
    try{const r=await fetch('/api/ask-ai',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});const d=await r.json();if(!r.ok)throw new Error(d.error||'Help request failed');if(helpAnswer)helpAnswer.textContent=d.answer+(d.mode==='AI'?'':'');}
    catch(e){if(helpAnswer)helpAnswer.textContent=e.message||'Help is temporarily unavailable.';}
  }
  $('aiForm')?.addEventListener('submit',e=>{e.preventDefault();const q=$('aiQuestion')?.value||'';askHelp(q);});

  updateSoundButton();
  resize(); seedHistory(); pollState(); connectWs();
  setInterval(pollState,1500);
  setInterval(()=>{ if(Date.now()<state.fastPollUntil) pollState(); },450);
  setInterval(tickTimers,1000);
})();
