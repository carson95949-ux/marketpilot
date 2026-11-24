from __future__ import annotations
import json, os, re, requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from access_db import authenticate_user, create_user, get_user, access_for_user, start_trial_for_user, trial_status_for_user, mark_purchase_for_user, verify, update_leaderboard_profile, leaderboard_users
from data_feed import coinbase_candles
from multi_db import connect, market_stats
from strategy import session_context
from polymarket_connections import builder_configured, refresh_status, start_authorization, submit_authorization, start_revocation, submit_revocation
try: import stripe
except Exception: stripe=None
ROOT=Path(__file__).resolve().parent; load_dotenv(ROOT/'.env'); CFG=json.loads((ROOT/'config.json').read_text()); KEY='polymarket_5m'; START=float(CFG.get('paper_starting_bankroll',1000.0)); TRIAL_MINUTES=int(os.getenv('TRIAL_MINUTES','30')); PURCHASE_PRICE_CENTS=int(os.getenv('PURCHASE_PRICE_CENTS','499')); COOKIE_NAME='marketpilot_access'
app=Flask(__name__); app.secret_key=os.getenv('MARKETPILOT_SECRET_KEY','dev-change-me-before-deploy'); app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true')
def _current_user():return get_user(session.get('user_id'))
def _access():
    u=_current_user(); return access_for_user(u['id']) if u else verify(request.cookies.get(COOKIE_NAME))
def _stripe_status():
    secret=os.getenv('STRIPE_SECRET_KEY','').strip(); approved=os.getenv('STRIPE_BUSINESS_APPROVED','false').lower()=='true'; test=secret.startswith('sk_test_'); return {'enabled':bool(stripe and secret and (test or approved)),'approved':approved,'test_mode':test,'secret':secret}
def _latest_snapshot():
    con=connect()
    try:r=con.execute('SELECT * FROM market_snapshots WHERE market_key=? ORDER BY id DESC LIMIT 1',(KEY,)).fetchone(); tr=con.execute('SELECT * FROM market_trades WHERE market_key=? ORDER BY id DESC LIMIT 12',(KEY,)).fetchall()
    finally:con.close()
    return (dict(r) if r else None),[dict(x) for x in tr]
def _num(v,d=None):
    try:return float(v) if v is not None else d
    except:return d
def _state_payload(access):
    row,trades=_latest_snapshot(); stats=market_stats(KEY,START)
    if not row:return {'ok':True,'ready':False,'access':{'kind':access['kind'],'remaining_seconds':access.get('remaining_seconds')},'message':'Start bot.py to begin collecting the current Polymarket BTC 5-minute market.'}
    action=str(row.get('action') or 'PASS').upper(); locked=bool(int(row.get('locked') or 0)); watch=str(row.get('watch_side') or '').upper(); mode=str(row.get('threshold_mode') or 'WATCHING')
    if locked and action in ('YES','NO'):state=f"BUY {'UP' if action=='YES' else 'DOWN'}";kind='up' if action=='YES' else 'down';badge='CONFIRMED · LOCKED'
    elif watch in ('YES','NO'):state=f"{'UP' if watch=='YES' else 'DOWN'} LEAN";kind='up' if watch=='YES' else 'down';badge=mode
    else:state='WAIT';kind='wait';badge='SCANNING'
    p=_num(row.get('p_yes'),.5); side='YES' if p>=.5 else 'NO'; fair=max(p,1-p); ask=_num(row.get('yes_ask') if side=='YES' else row.get('no_ask'),0); prof=CFG['market_profiles'][KEY]; sess=session_context(CFG); req=float(prof['min_net_edge'])+float(sess['edge_penalty']); cost=float(CFG.get('polymarket_cost_buffer',.02)); maxbuy=max(.01,min(.99,fair-cost-req)); edge=(fair-ask-cost) if ask else None
    try:snap=datetime.fromisoformat(str(row['ts']).replace('Z','+00:00')); deadline=int((snap.timestamp()+max(0,_num(row.get('seconds_left'),0)))*1000)
    except:deadline=int(datetime.now(timezone.utc).timestamp()*1000)
    cc=int(row.get('confirmation_count') or 0); cr=max(1,int(row.get('confirmation_required') or CFG['decision_confirmation']['required_scans'])); recent=[]
    for t in trades:recent.append({'id':t.get('id'),'opened_ts':t.get('opened_ts'),'side':'UP' if str(t.get('side')).upper()=='YES' else 'DOWN' if str(t.get('side')).upper()=='NO' else t.get('side'),'entry_price':_num(t.get('entry_price')),'model_probability':_num(t.get('model_probability')),'net_edge':_num(t.get('net_edge')),'status':t.get('status'),'result':t.get('result'),'pnl':_num(t.get('pnl'))})
    return {'ok':True,'ready':True,'access':{'kind':access['kind'],'remaining_seconds':access.get('remaining_seconds')},'market':{'market_id':row.get('market_id'),'state':state,'state_kind':kind,'badge':badge,'reason':row.get('reason') or 'Reading BTC price action and order-book pressure.','deadline_ms':deadline,'target':_num(row.get('target')),'yes_ask':_num(row.get('yes_ask')),'no_ask':_num(row.get('no_ask')),'p_up':p,'fair':fair,'lean_side':'UP' if side=='YES' else 'DOWN','ask':ask,'max_buy':maxbuy,'edge':edge,'entry_available':bool(ask and ask<=maxbuy),'chart_read':row.get('chart_read') or '—','book_imbalance':_num(row.get('book_imbalance')),'confirmation_count':cc,'confirmation_required':cr,'confirmation_progress':min(100,100*cc/cr),'session_label':sess['label']},'stats':stats,'trades':recent}
@app.get('/')
def home():return render_template('index.html',price=f'${PURCHASE_PRICE_CENTS/100:.2f}',user=_current_user(),minutes=TRIAL_MINUTES)
@app.route('/signup',methods=['GET','POST'])
def signup():
    if _current_user():return redirect(url_for('account'))
    err=None
    if request.method=='POST':
        try:u=create_user(request.form.get('email',''),request.form.get('password',''));session['user_id']=u['id'];return redirect(request.args.get('next') or url_for('trial'))
        except Exception as e:err=str(e)
    return render_template('signup.html',error=err,next=request.args.get('next',''))
@app.route('/login',methods=['GET','POST'])
def login():
    if _current_user():return redirect(url_for('account'))
    err=None
    if request.method=='POST':
        u=authenticate_user(request.form.get('email',''),request.form.get('password',''))
        if not u:err='Email or password is incorrect.'
        else:session['user_id']=u['id'];return redirect(request.args.get('next') or (url_for('tool') if access_for_user(u['id']) else url_for('account')))
    return render_template('login.html',error=err,next=request.args.get('next',''))
@app.post('/logout')
def logout():session.clear();return redirect(url_for('home'))
@app.get('/trial')
def trial():
    u=_current_user()
    if not u:return redirect(url_for('signup',next='/trial'))
    if access_for_user(u['id']):return redirect(url_for('tool'))
    return render_template('trial.html',minutes=TRIAL_MINUTES,price=f'${PURCHASE_PRICE_CENTS/100:.2f}',trial=trial_status_for_user(u['id']))
@app.post('/trial/start')
def trial_start():
    u=_current_user()
    if not u:return redirect(url_for('signup',next='/trial'))
    r=start_trial_for_user(u['id'],TRIAL_MINUTES);return redirect(url_for('purchase') if r and r.get('kind')=='expired' else url_for('tool'))
@app.get('/purchase')
def purchase():
    u=_current_user();st=_stripe_status();a=access_for_user(u['id']) if u else None
    if a and a['kind']=='purchase':return redirect(url_for('tool'))
    return render_template('purchase.html',price=f'${PURCHASE_PRICE_CENTS/100:.2f}',checkout_configured=st['enabled'],stripe_approved=st['approved'],stripe_test_mode=st['test_mode'],user=u)
@app.post('/checkout')
def checkout():
    u=_current_user()
    if not u:return redirect(url_for('signup',next='/purchase'))
    st=_stripe_status()
    if not st['enabled']:return render_template('purchase.html',price=f'${PURCHASE_PRICE_CENTS/100:.2f}',checkout_configured=False,stripe_approved=st['approved'],stripe_test_mode=st['test_mode'],user=u,error='Stripe Checkout is not enabled. Test mode works with an sk_test_ key; live mode should only be enabled after Stripe approves this business.'),400
    stripe.api_key=st['secret']; cs=stripe.checkout.Session.create(mode='payment',client_reference_id=str(u['id']),customer_email=u['email'],metadata={'marketpilot_user_id':str(u['id'])},line_items=[{'price_data':{'currency':'usd','product_data':{'name':'MarketPilot BTC 5M — Lifetime Access'},'unit_amount':PURCHASE_PRICE_CENTS},'quantity':1}],success_url=url_for('purchase_success',_external=True)+'?session_id={CHECKOUT_SESSION_ID}',cancel_url=url_for('purchase',_external=True));return redirect(cs.url,303)
def _mark(cs):
    if getattr(cs,'payment_status',None)!='paid':return False
    uid=getattr(cs,'client_reference_id',None) or (getattr(cs,'metadata',{}) or {}).get('marketpilot_user_id')
    if not uid:return False
    mark_purchase_for_user(int(uid),getattr(cs,'id',None),str(getattr(cs,'customer',None) or ''));return True
@app.get('/purchase-success')
def purchase_success():
    u=_current_user();sid=request.args.get('session_id','');st=_stripe_status()
    if not u or not sid or not st['enabled']:return redirect(url_for('purchase'))
    stripe.api_key=st['secret']; cs=stripe.checkout.Session.retrieve(sid)
    if not _mark(cs):return redirect(url_for('purchase'))
    return render_template('payment_success.html')
@app.post('/stripe/webhook')
def stripe_webhook():
    st=_stripe_status();secret=os.getenv('STRIPE_WEBHOOK_SECRET','').strip()
    if not st['enabled'] or not secret:return ('Webhook not configured',400)
    try:event=stripe.Webhook.construct_event(request.get_data(),request.headers.get('Stripe-Signature',''),secret)
    except Exception:return ('Invalid webhook',400)
    if event.get('type')=='checkout.session.completed':
        try:_mark(event['data']['object'])
        except:pass
    return ('',200)
def _performance_since(start_iso):
    try:start=datetime.fromisoformat(str(start_iso).replace('Z','+00:00'))
    except Exception:start=datetime(1970,1,1,tzinfo=timezone.utc)
    con=connect()
    try:
        rows=con.execute("SELECT opened_ts,contracts,entry_price,pnl FROM market_trades WHERE market_key=? AND status='SETTLED' ORDER BY opened_ts",(KEY,)).fetchall()
    finally:con.close()
    chosen=[]
    for r in rows:
        try:t=datetime.fromisoformat(str(r['opened_ts']).replace('Z','+00:00'))
        except Exception:continue
        if t>=start:chosen.append(r)
    pnl=sum(float(r['pnl'] or 0) for r in chosen)
    risk=sum(max(.01,float(r['contracts'] or 0)*float(r['entry_price'] or 0)) for r in chosen)
    wins=sum(1 for r in chosen if float(r['pnl'] or 0)>0)
    return {'trades':len(chosen),'wins':wins,'win_rate':wins/len(chosen) if chosen else 0.0,'pnl':pnl,'roi':(pnl/risk if risk else 0.0)}

DEMO_LEADERBOARD = [
    {'user_id':'demo-1','name':'ClutchCarson23','roi':0.428,'win_rate':0.679,'trades':68,'pnl':0.0,'wins':46,'eligible':True,'opt_in':True,'demo':True},
    {'user_id':'demo-2','name':'RedZoneRyan','roi':0.409,'win_rate':0.671,'trades':73,'pnl':0.0,'wins':49,'eligible':True,'opt_in':True,'demo':True},
    {'user_id':'demo-3','name':'MasonR','roi':0.396,'win_rate':0.667,'trades':72,'pnl':0.0,'wins':48,'eligible':True,'opt_in':True,'demo':True},
    {'user_id':'demo-4','name':'AlexW7','roi':0.382,'win_rate':0.658,'trades':71,'pnl':0.0,'wins':47,'eligible':True,'opt_in':True,'demo':True},
    {'user_id':'demo-5','name':'ColeB','roi':0.369,'win_rate':0.657,'trades':67,'pnl':0.0,'wins':44,'eligible':True,'opt_in':True,'demo':True},
    {'user_id':'demo-6','name':'TylerK34','roi':0.354,'win_rate':0.647,'trades':62,'pnl':0.0,'wins':40,'eligible':True,'opt_in':True,'demo':True},
]

def _leaderboard_context(current_user_id):
    real_items=[]; current=None
    for u in leaderboard_users():
        start=u.get('trial_started_at') or u.get('created_at')
        perf=_performance_since(start)
        name=(u.get('leaderboard_name') or f"Pilot {int(u['id']):03d}")
        item={'user_id':int(u['id']),'name':name,**perf,'eligible':perf['trades']>=1,'opt_in':bool(int(u.get('leaderboard_opt_in') or 0)),'demo':False}
        if int(u['id'])==int(current_user_id): current=item
        if item['opt_in'] and item['eligible']: real_items.append(item)
    show_demo=os.getenv('MARKETPILOT_DEMO_LEADERBOARD','true').lower()=='true' and len(real_items)<5
    items=list(real_items)+(list(DEMO_LEADERBOARD) if show_demo else [])
    items.sort(key=lambda x:(x['roi'],x['win_rate'],x['trades']),reverse=True)
    for i,x in enumerate(items,1):x['rank']=i
    if current:
        match=next((x for x in items if x['user_id']==int(current_user_id)),None)
        if match: current=match
    return {'top':items[:10],'current':current,'eligible_count':len(items),'real_eligible_count':len(real_items),'demo_mode':show_demo,'demo_count':len(DEMO_LEADERBOARD) if show_demo else 0}

def _local_help_answer(q,payload):
    low=q.lower(); m=(payload or {}).get('market',{}) if payload else {}
    if 'edge' in low:return 'Estimated edge is MarketPilot’s fair probability minus the executable contract price and modeled trading costs. A positive edge is an estimate, not a guarantee.'
    if 'max buy' in low or 'entry zone' in low:return 'Max buy price is the highest contract price MarketPilot estimates still clears its configured edge threshold. If the ask moves above it, the tool switches back toward WAIT instead of encouraging a chase.'
    if 'price to beat' in low or 'target' in low:return 'Price to Beat is the current round target proxy shown on the chart. It resets each 5-minute round. Polymarket ultimately settles using its stated Chainlink reference, so MarketPilot treats its fast BTC feed as a proxy.'
    if 'sound' in low:return 'Turn Sound on in the header. You will hear a neutral rising tone when BTC crosses above the target, a falling tone when it crosses below, and a short chime when a tracked paper trade settles profitable.'
    if 'connect' in low or 'polymarket' in low:return 'Use the large Connect Polymarket section near the bottom or My Account. MarketPilot uses a scoped trading session and should never ask you to paste your main wallet private key.'
    if 'buy' in low or 'trade' in low:
        state=m.get('state','WAIT'); edge=m.get('edge'); ask=m.get('ask'); maxbuy=m.get('max_buy')
        return f"The current MarketPilot state is {state}. Current ask: {cents_py(ask)}; max-buy estimate: {cents_py(maxbuy)}; modeled edge: {pct_py(edge)}. Treat a confirmed signal as research support, not a guarantee, and do not increase size to recover a loss."
    return 'Ask me about the current signal, edge, max buy price, target, countdown, bankroll rules, account connection, or how a MarketPilot feature works.'

def cents_py(v):
    try:return f"{round(float(v)*100)}¢"
    except:return '—'

def pct_py(v):
    try:return f"{float(v)*100:.1f}%"
    except:return '—'

@app.get('/account')
def account():
    u=_current_user()
    if not u:return redirect(url_for('login',next='/account'))
    a=access_for_user(u['id']);return render_template('account.html',user=u,access=a,trial=trial_status_for_user(u['id']),price=f'${PURCHASE_PRICE_CENTS/100:.2f}',builder_configured=builder_configured(),leaderboard=_leaderboard_context(u['id']),saved=request.args.get('saved')=='1')
@app.post('/account/leaderboard')
def account_leaderboard():
    u=_current_user()
    if not u:return redirect(url_for('login',next='/account'))
    try:update_leaderboard_profile(u['id'],request.form.get('leaderboard_name',''),request.form.get('leaderboard_opt_in')=='on')
    except Exception as x:
        a=access_for_user(u['id']);return render_template('account.html',user=get_user(u['id']),access=a,trial=trial_status_for_user(u['id']),price=f'${PURCHASE_PRICE_CENTS/100:.2f}',builder_configured=builder_configured(),leaderboard=_leaderboard_context(u['id']),leaderboard_error=str(x),saved=False),400
    return redirect(url_for('account',saved='1')+'#rankings')
def _need_access():
    u=_current_user();a=access_for_user(u['id']) if u else None
    if not u:return None,None,(jsonify({'ok':False,'error':'Sign in first.'}),401)
    if not a:return u,None,(jsonify({'ok':False,'error':'Active access is required.'}),403)
    return u,a,None
@app.get('/api/polymarket/connection')
def pc():
    u,a,e=_need_access();return e if e else jsonify({'ok':True,'builder_configured':builder_configured(),'connection':refresh_status(u['id'])})
@app.post('/api/polymarket/connect/start')
def pcs():
    u,a,e=_need_access()
    if e:return e
    try:
        p=request.get_json(silent=True) or {};return jsonify({'ok':True,**start_authorization(u['id'],p.get('owner_address'),p.get('deposit_wallet'),p.get('session_address'),p.get('session_private_key'),p.get('calldata'),p.get('valid_until'))})
    except Exception as x:return jsonify({'ok':False,'error':str(x)}),400
@app.post('/api/polymarket/connect/submit')
def pcsub():
    u,a,e=_need_access()
    if e:return e
    try:return jsonify({'ok':True,**submit_authorization(u['id'],(request.get_json(silent=True) or {}).get('signature'))})
    except Exception as x:return jsonify({'ok':False,'error':str(x)}),400
@app.post('/api/polymarket/revoke/start')
def prs():
    u,a,e=_need_access()
    if e:return e
    try:return jsonify({'ok':True,**start_revocation(u['id'],(request.get_json(silent=True) or {}).get('calldata'))})
    except Exception as x:return jsonify({'ok':False,'error':str(x)}),400
@app.post('/api/polymarket/revoke/submit')
def prsub():
    u,a,e=_need_access()
    if e:return e
    try:return jsonify({'ok':True,**submit_revocation(u['id'],(request.get_json(silent=True) or {}).get('signature'))})
    except Exception as x:return jsonify({'ok':False,'error':str(x)}),400
@app.get('/tool')
def tool():
    u=_current_user()
    if not u:return redirect(url_for('login',next='/tool'))
    a=access_for_user(u['id'])
    if not a:return redirect(url_for('purchase'))
    return render_template('tool.html',access_kind=a['kind'],price=f'${PURCHASE_PRICE_CENTS/100:.2f}')
@app.get('/api/state')
def state_api():
    a=_access()
    if not a:return jsonify({'ok':False,'error':'access_expired','redirect':'/purchase'}),403
    return jsonify(_state_payload(a))
@app.get('/api/btc-history')
def hist():
    if not _access():return jsonify({'ok':False,'error':'access_expired','redirect':'/purchase'}),403
    try:
        c=coinbase_candles(minutes=60);return jsonify({'ok':True,'points':[{'t':int(float(r.time)*1000),'p':float(r.close)} for r in c.tail(60).itertuples()]})
    except Exception as e:return jsonify({'ok':False,'error':str(e),'points':[]}),502
@app.post('/api/ask-ai')
def ask_ai():
    u,a,e=_need_access()
    if e:return e
    body=request.get_json(silent=True) or {}; q=str(body.get('question') or '').strip()
    if not q:return jsonify({'ok':False,'error':'Ask a question first.'}),400
    if len(q)>700:return jsonify({'ok':False,'error':'Keep questions under 700 characters.'}),400
    payload=_state_payload(a); fallback=_local_help_answer(q,payload)
    api_key=os.getenv('OPENAI_API_KEY','').strip()
    if not api_key:return jsonify({'ok':True,'answer':fallback,'mode':'built-in help'})
    m=(payload or {}).get('market',{})
    context=f"Current state={m.get('state','WAIT')}; ask={m.get('ask')}; max_buy={m.get('max_buy')}; edge={m.get('edge')}; fair={m.get('fair')}; chart_read={m.get('chart_read')}; book_imbalance={m.get('book_imbalance')}; countdown deadline={m.get('deadline_ms')}."
    instructions=("You are MarketPilot Help AI inside a Polymarket BTC 5-minute research tool. Explain the interface and current displayed metrics clearly and briefly. "
                  "Do not promise profit, encourage chasing losses, suggest increasing risk after losses, or manufacture certainty. If asked whether to trade, describe what the current MarketPilot state says and the relevant max-buy/edge, then remind the user it is an estimate. Never request private keys, passwords, or wallet secrets.")
    try:
        r=requests.post('https://api.openai.com/v1/responses',headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},json={'model':os.getenv('OPENAI_MODEL','gpt-6-luna'),'instructions':instructions,'input':f"{context}\n\nUser question: {q}"},timeout=18)
        r.raise_for_status(); data=r.json(); texts=[]
        for item in data.get('output',[]) or []:
            for c in item.get('content',[]) or []:
                if c.get('type')=='output_text' and c.get('text'):texts.append(c['text'])
        answer='\n'.join(texts).strip() or fallback
        return jsonify({'ok':True,'answer':answer,'mode':'AI'})
    except Exception:
        return jsonify({'ok':True,'answer':fallback,'mode':'built-in help'})

@app.get('/health')
def health():return jsonify({'ok':True})
if __name__=='__main__':app.run(host='127.0.0.1',port=int(os.getenv('PORT','8765')),debug=False,threaded=True)
