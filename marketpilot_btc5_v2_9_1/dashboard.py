from __future__ import annotations

import html, json, sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from data_feed import coinbase_candles, coinbase_spot
from multi_db import connect, market_stats
from strategy import session_context

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text())
KEY = "polymarket_5m"
START = float(CFG.get("paper_starting_bankroll", 1000))

st.set_page_config(page_title="MarketPilot · BTC 5M", page_icon="M", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Manrope:wght@700;800&display=swap');
:root{--bg:#070a08;--panel:#0d120f;--panel2:#111712;--line:#203025;--text:#f4f7f5;--muted:#819087;--green:#7df27f;--red:#ff727d;--amber:#f3c765;--cyan:#86d8ff}
html,body,[class*="css"]{font-family:Inter,sans-serif}.stApp{background:radial-gradient(circle at 20% -10%,rgba(125,242,127,.12),transparent 30%),#070a08;color:var(--text)}
.block-container{max-width:1180px;padding-top:1.2rem;padding-bottom:3rem}header,#MainMenu,footer{visibility:hidden}.stButton button{border-radius:12px}
.top{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:18px}.brand{display:flex;align-items:center;gap:12px}.mark{width:42px;height:42px;border-radius:13px;background:linear-gradient(145deg,#92ff8c,#45b7ff);color:#071009;font:900 18px Manrope;display:flex;align-items:center;justify-content:center}.name{font:800 24px Manrope;letter-spacing:-.8px}.sub{font-size:11px;color:var(--muted);margin-top:3px}.status{font-size:10px;font-weight:800;letter-spacing:.8px;padding:7px 10px;border:1px solid #294030;border-radius:999px;color:#87ef94;background:#0d1710}
.hero{display:grid;grid-template-columns:1.35fr .65fr;gap:12px}.card{border:1px solid var(--line);background:linear-gradient(180deg,#0e1410,#0a0f0c);border-radius:22px;padding:20px}.eyebrow{font-size:10px;color:var(--muted);font-weight:800;letter-spacing:1.1px;text-transform:uppercase}.state{font:900 clamp(42px,7vw,72px) Manrope;letter-spacing:-3px;margin:12px 0 3px}.state.up{color:var(--green)}.state.down{color:var(--red)}.state.wait{color:#e8eee9}.reason{color:#93a099;font-size:12px;line-height:1.5;max-width:720px}.lock{display:inline-block;margin-top:12px;padding:7px 10px;border:1px solid #2c4431;border-radius:10px;color:#8ff59b;background:#0a160d;font-size:10px;font-weight:900;letter-spacing:.6px}.count-title{font-size:10px;color:var(--muted);font-weight:800;letter-spacing:1px;text-transform:uppercase}.count-wrap{margin-top:13px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.metric{border:1px solid var(--line);border-radius:16px;padding:14px;background:#0b100d}.mk{font-size:9px;color:#718078;text-transform:uppercase;letter-spacing:.8px;font-weight:850}.mv{font:800 24px Manrope;margin-top:5px;letter-spacing:-.6px}.mf{font-size:10px;color:#6f7c74;margin-top:4px}.section{border:1px solid var(--line);background:#0b100d;border-radius:20px;padding:17px;margin-top:12px}.stitle{font:800 16px Manrope;letter-spacing:-.3px}.ssub{font-size:11px;color:#7e8b83;margin-top:3px;line-height:1.45}.entry{display:grid;grid-template-columns:1.1fr .9fr;gap:12px}.zone{border:1px solid #2a4030;background:linear-gradient(160deg,rgba(125,242,127,.08),rgba(10,16,12,.98));border-radius:18px;padding:18px}.zone-title{font-size:10px;color:#8da095;font-weight:850;letter-spacing:1px;text-transform:uppercase}.zone-price{font:900 44px Manrope;letter-spacing:-2px;margin:5px 0}.zone-sub{font-size:11px;color:#7f8c84}.bar{height:7px;background:#172019;border-radius:99px;overflow:hidden;margin-top:14px}.fill{height:100%;background:linear-gradient(90deg,#45b7ff,#7df27f);border-radius:99px}.perf{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.small{border:1px solid var(--line);border-radius:14px;padding:12px;background:#0a0f0c}.small .v{font:800 21px Manrope;margin-top:5px}.small .k{font-size:9px;color:#728078;text-transform:uppercase;letter-spacing:.7px;font-weight:800}
@media(max-width:850px){.hero,.entry{grid-template-columns:1fr}.grid4,.perf{grid-template-columns:repeat(2,1fr)}.top{align-items:flex-start}.status{display:none}}@media(max-width:520px){.grid4,.perf{grid-template-columns:1fr}.block-container{padding-left:.75rem;padding-right:.75rem}.state{font-size:46px}}
</style>
""", unsafe_allow_html=True)


def esc(x): return html.escape(str(x if x is not None else ""))
def pct(x):
    try:return f"{float(x)*100:.1f}%"
    except:return "—"
def cents(x):
    try:return f"{float(x)*100:.0f}¢"
    except:return "—"
def money(x):
    try:return f"${float(x):,.2f}"
    except:return "—"


def load_data():
    con=connect()
    try:
        snaps=pd.read_sql_query("SELECT * FROM market_snapshots WHERE market_key=? ORDER BY id DESC LIMIT 600",con,params=(KEY,))
        trades=pd.read_sql_query("SELECT * FROM market_trades WHERE market_key=? ORDER BY id DESC LIMIT 100",con,params=(KEY,))
    finally:con.close()
    return snaps,trades

@st.cache_data(ttl=2,show_spinner=False)
def market_feed():
    c=coinbase_candles(minutes=60)
    try:s=coinbase_spot()
    except:s=float(c.iloc[-1]["close"]) if not c.empty else None
    return c,s


def deadline_ms(row):
    try:
        snap=pd.to_datetime(row["ts"],utc=True); secs=max(0,float(row["seconds_left"] or 0))
        return int((snap+pd.Timedelta(seconds=secs)).timestamp()*1000)
    except:return int(pd.Timestamp.now(tz="UTC").timestamp()*1000)


def countdown(row):
    d=deadline_ms(row); now=int(pd.Timestamp.now(tz="UTC").timestamp()*1000)
    components.html(f"""
    <div style='font-family:Inter;color:#f4f7f5;background:transparent'><div id='cd' style='font-size:56px;font-weight:900;letter-spacing:-2.5px'>--:--</div><div style='height:6px;background:#18201a;border-radius:99px;overflow:hidden;margin-top:12px'><div id='cb' style='height:100%;width:100%;background:linear-gradient(90deg,#45b7ff,#7df27f)'></div></div></div>
    <script>const deadline={d},offset={now}-Date.now();const initial=Math.max(1,Math.ceil((deadline-({now}))/1000));function t(){{const s=Math.max(0,Math.ceil((deadline-(Date.now()+offset))/1000));document.getElementById('cd').textContent=Math.floor(s/60)+':'+String(s%60).padStart(2,'0');document.getElementById('cb').style.width=(100*s/initial)+'%';}}t();setInterval(t,100);</script>
    """,height=92)


def live_chart(candles,target):
    d=candles.copy();d["time"]=pd.to_numeric(d["time"],errors="coerce");d["close"]=pd.to_numeric(d["close"],errors="coerce");d=d.dropna(subset=["time","close"]).tail(45)
    seed=json.dumps([{"t":int(float(r.time)*1000),"p":float(r.close)} for r in d.itertuples()],separators=(",",":")); tj="null" if target is None or pd.isna(target) else str(float(target))
    components.html(f"""
    <div id='wrap' style='height:400px;position:relative;background:#080d0a;border-radius:14px;overflow:hidden;font-family:Inter'><canvas id='cv' style='width:100%;height:100%'></canvas><div id='px' style='position:absolute;right:12px;top:10px;color:#f4f7f5;font-size:20px;font-weight:800'>BTC —</div><div id='ws' style='position:absolute;left:12px;top:12px;color:#6f7d74;font-size:10px;font-weight:800;letter-spacing:.7px'>CONNECTING</div></div>
    <script>(()=>{{const wrap=document.getElementById('wrap'),cv=document.getElementById('cv'),ctx=cv.getContext('2d'),px=document.getElementById('px'),wsLabel=document.getElementById('ws');let pts={seed},target={tj},last=0,horizon=30*60*1000;function resize(){{let dpr=window.devicePixelRatio||1,r=wrap.getBoundingClientRect();cv.width=r.width*dpr;cv.height=r.height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw()}}new ResizeObserver(resize).observe(wrap);function add(t,p){{if(t-last<300&&pts.length)pts[pts.length-1]={{t,p}};else{{pts.push({{t,p}});last=t}}while(pts.length>2&&pts[0].t<Date.now()-horizon)pts.shift();px.textContent='BTC $'+p.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});draw()}}function draw(){{let W=wrap.clientWidth,H=wrap.clientHeight;if(!W||pts.length<2)return;ctx.clearRect(0,0,W,H);let L=14,R=74,T=44,B=24,minT=Date.now()-horizon,v=pts.filter(x=>x.t>=minT);if(v.length<2)return;let vals=v.map(x=>x.p);if(target!==null)vals.push(target);let lo=Math.min(...vals),hi=Math.max(...vals),pad=Math.max((hi-lo)*.14,hi*.0002);lo-=pad;hi+=pad;let X=t=>L+(t-minT)/horizon*(W-L-R),Y=p=>T+(hi-p)/(hi-lo)*(H-T-B);ctx.strokeStyle='#18221b';ctx.fillStyle='#6e7b73';ctx.font='10px Inter';for(let i=0;i<5;i++){{let y=T+(H-T-B)*i/4;ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-R+8,y);ctx.stroke();ctx.fillText('$'+Math.round(hi-(hi-lo)*i/4).toLocaleString(),W-R+12,y+3)}}if(target!==null){{let y=Y(target);ctx.save();ctx.setLineDash([6,5]);ctx.strokeStyle='#f3c765';ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-R+8,y);ctx.stroke();ctx.restore();ctx.fillStyle='#f3c765';ctx.fillText('PRICE TO BEAT',L+5,Math.max(T+11,y-7))}}let g=ctx.createLinearGradient(0,T,0,H-B);g.addColorStop(0,'rgba(125,242,127,.16)');g.addColorStop(1,'rgba(125,242,127,0)');ctx.beginPath();v.forEach((q,i)=>i?ctx.lineTo(X(q.t),Y(q.p)):ctx.moveTo(X(q.t),Y(q.p)));ctx.lineTo(X(v[v.length-1].t),H-B);ctx.lineTo(X(v[0].t),H-B);ctx.closePath();ctx.fillStyle=g;ctx.fill();ctx.beginPath();v.forEach((q,i)=>i?ctx.lineTo(X(q.t),Y(q.p)):ctx.moveTo(X(q.t),Y(q.p)));ctx.strokeStyle='#7df27f';ctx.lineWidth=2.1;ctx.stroke()}}function connect(){{let w=new WebSocket('wss://ws-feed.exchange.coinbase.com');w.onopen=()=>{{wsLabel.textContent='● LIVE BTC-USD';wsLabel.style.color='#7df27f';w.send(JSON.stringify({{type:'subscribe',product_ids:['BTC-USD'],channels:['ticker']}}))}};w.onmessage=e=>{{try{{let m=JSON.parse(e.data);if(m.type==='ticker'&&m.price)add(Date.parse(m.time)||Date.now(),Number(m.price))}}catch(_e){{}}}};w.onclose=()=>{{wsLabel.textContent='RECONNECTING';wsLabel.style.color='#f3c765';setTimeout(connect,1200)}}}}if(pts.length)px.textContent='BTC $'+pts[pts.length-1].p.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});resize();connect()}})();</script>
    """,height=410)

snaps,trades=load_data(); candles,spot=market_feed(); row=snaps.iloc[0] if not snaps.empty else None
stats=market_stats(KEY,START)

st.markdown("<div class='top'><div class='brand'><div class='mark'>M</div><div><div class='name'>MarketPilot</div><div class='sub'>Polymarket Bitcoin · 5-minute edge engine</div></div></div><div class='status'>● LIVE MARKET</div></div>",unsafe_allow_html=True)

if row is None:
    st.warning("Start bot.py to begin collecting the current Polymarket BTC 5-minute market.")
    st.stop()

action=str(row.get("action") or "PASS").upper(); locked=bool(int(row.get("locked") or 0)); watch=str(row.get("watch_side") or "").upper(); mode=str(row.get("threshold_mode") or "WATCHING")
if locked and action in ("YES","NO"):
    state=f"BUY {'UP' if action=='YES' else 'DOWN'}"; cls="up" if action=="YES" else "down"; badge="🔒 CONFIRMED · LOCKED"
elif watch in ("YES","NO"):
    state=f"{'UP' if watch=='YES' else 'DOWN'} LEAN"; cls="up" if watch=="YES" else "down"; badge=mode
else:
    state="WAIT"; cls="wait"; badge="SCANNING"

p_up=float(row.get("p_yes") or .5); lean_side="YES" if p_up>=.5 else "NO"; fair=max(p_up,1-p_up); ask=float(row.get("yes_ask") if lean_side=="YES" else row.get("no_ask") or 0); profile=CFG["market_profiles"][KEY]; sess=session_context(CFG); req=float(profile["min_net_edge"])+float(sess["edge_penalty"]); cost=float(CFG.get("polymarket_cost_buffer",.02)); max_buy=max(.01,min(.99,fair-cost-req)); edge=fair-ask-cost if ask else None
conf_count=int(row.get("confirmation_count") or 0); conf_req=max(1,int(row.get("confirmation_required") or CFG["decision_confirmation"]["required_scans"])); progress=min(100,100*conf_count/conf_req)

target=float(row.get("target") or 0); reason=esc(row.get("reason") or "MarketPilot is reading BTC price action, target distance, market price and order-book pressure.")
st.markdown(f"""
<div class='hero'><div class='card'><div class='eyebrow'>Current BTC 5-minute decision</div><div class='state {cls}'>{state}</div><div class='reason'>{reason}</div><div class='lock'>{esc(badge)}</div><div class='bar'><div class='fill' style='width:{progress:.0f}%'></div></div></div><div class='card'><div class='count-title'>Market closes in</div><div class='count-wrap'>""",unsafe_allow_html=True)
countdown(row)
st.markdown("</div></div></div>",unsafe_allow_html=True)

st.markdown(f"""
<div class='grid4'>
<div class='metric'><div class='mk'>BTC live</div><div class='mv'>{money(spot)}</div><div class='mf'>Coinbase live display feed</div></div>
<div class='metric'><div class='mk'>Price to beat</div><div class='mv'>{money(target)}</div><div class='mf'>Opening-price proxy used by the model</div></div>
<div class='metric'><div class='mk'>UP price</div><div class='mv'>{cents(row.get('yes_ask'))}</div><div class='mf'>Current executable ask</div></div>
<div class='metric'><div class='mk'>DOWN price</div><div class='mv'>{cents(row.get('no_ask'))}</div><div class='mf'>Current executable ask</div></div>
</div>
""",unsafe_allow_html=True)

side_label="UP" if lean_side=="YES" else "DOWN"
zone_status="ENTRY AVAILABLE" if ask and ask<=max_buy else "WAIT FOR PRICE"
st.markdown(f"""
<div class='section'><div class='stitle'>MarketPilot Entry Zone</div><div class='ssub'>Direction alone is not enough. MarketPilot estimates what the selected side is worth and the highest price that still clears the configured edge threshold.</div><div class='entry' style='margin-top:12px'><div class='zone'><div class='zone-title'>{side_label} maximum buy price</div><div class='zone-price'>{cents(max_buy)}</div><div class='zone-sub'>{zone_status} · Current {side_label} ask {cents(ask)}</div></div><div class='grid4' style='grid-template-columns:repeat(2,1fr);margin-top:0'><div class='metric'><div class='mk'>Fair probability</div><div class='mv'>{pct(fair)}</div><div class='mf'>Model value for {side_label}</div></div><div class='metric'><div class='mk'>Estimated edge</div><div class='mv'>{pct(edge)}</div><div class='mf'>After configured cost buffer</div></div><div class='metric'><div class='mk'>Chart read</div><div class='mv' style='font-size:17px'>{esc(row.get('chart_read') or '—')}</div><div class='mf'>Price-action confirmation</div></div><div class='metric'><div class='mk'>Book pressure</div><div class='mv'>{'—' if pd.isna(row.get('book_imbalance')) else f"{float(row.get('book_imbalance')):+.2f}"}</div><div class='mf'>Positive supports UP</div></div></div></div></div>
""",unsafe_allow_html=True)

st.markdown("<div class='section'><div class='stitle'>Live BTC vs price to beat</div><div class='ssub'>The chart streams BTC trades in the browser. The bot reads the underlying candle data rather than the picture.</div>",unsafe_allow_html=True)
live_chart(candles,target)
st.markdown("</div>",unsafe_allow_html=True)

st.markdown(f"""
<div class='section'><div class='stitle'>Track record</div><div class='ssub'>Only confirmed MarketPilot trades count toward these numbers.</div><div class='perf' style='margin-top:12px'>
<div class='small'><div class='k'>Paper P&L</div><div class='v'>{money(stats['pnl'])}</div></div>
<div class='small'><div class='k'>Win rate</div><div class='v'>{pct(stats['win_rate']) if stats['settled'] else '—'}</div></div>
<div class='small'><div class='k'>Current streak</div><div class='v'>{stats['current_streak']}</div></div>
<div class='small'><div class='k'>Settled trades</div><div class='v'>{stats['settled']}</div></div>
</div></div>
""",unsafe_allow_html=True)

if not trades.empty:
    show=trades[[c for c in ["opened_ts","side","entry_price","model_probability","net_edge","status","result","pnl"] if c in trades.columns]].copy()
    if "side" in show: show["side"]=show["side"].map({"YES":"UP","NO":"DOWN"}).fillna(show["side"])
    st.markdown("<div class='section'><div class='stitle'>Recent confirmed trades</div><div class='ssub'>Newest first.</div>",unsafe_allow_html=True)
    st.dataframe(show.head(20),use_container_width=True,hide_index=True)
    st.markdown("</div>",unsafe_allow_html=True)

st.caption("MarketPilot is a research/trading tool. Model probabilities are estimates, not guarantees. Paper mode is the default.")

# Refresh only the Streamlit data layer; the countdown and BTC line update independently in-browser.
components.html("<script>setTimeout(()=>window.parent.location.reload(),2500)</script>",height=0)
