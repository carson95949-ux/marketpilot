from __future__ import annotations
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MARKETPILOT_DATA_DIR", str(ROOT)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "bot_data.sqlite3"
SNAPSHOT_COLUMNS = {
    "chart_read":"TEXT","chart_score":"REAL","locked":"INTEGER DEFAULT 0",
    "adaptive":"INTEGER DEFAULT 0","skipped_rounds":"INTEGER DEFAULT 0",
    "threshold_mode":"TEXT","strategy_type":"TEXT","pair_cost":"REAL",
    "maker_pair_cost":"REAL","maker_pair_edge":"REAL",
    "book_imbalance":"REAL","watch_side":"TEXT","confirmation_count":"INTEGER DEFAULT 0","confirmation_required":"INTEGER DEFAULT 0"
}
TRADE_COLUMNS = {
    "hedged":"INTEGER DEFAULT 0","hedge_side":"TEXT","hedge_price":"REAL",
    "hedge_cost_per_contract":"REAL DEFAULT 0","strategy_type":"TEXT DEFAULT 'DIRECTIONAL'"
}
STATE_COLUMNS = {
    "candidate_side":"TEXT","candidate_count":"INTEGER DEFAULT 0","candidate_updated_ts":"TEXT"
}

def _ensure_columns(con, table, columns):
    existing={r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    for name,ddl in columns.items():
        if name not in existing: con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

def connect():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS market_snapshots(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, market_key TEXT NOT NULL,
      platform TEXT NOT NULL, timeframe TEXT NOT NULL, market_id TEXT, seconds_left REAL,
      target REAL,target_quality TEXT,reference REAL,reference_source TEXT,yes_bid REAL,yes_ask REAL,
      no_bid REAL,no_ask REAL,p_yes REAL,action TEXT,net_edge REAL,reason TEXT)""")
    _ensure_columns(con,"market_snapshots",SNAPSHOT_COLUMNS)
    con.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshots_key_id ON market_snapshots(market_key,id)")
    con.execute("""CREATE TABLE IF NOT EXISTS market_trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT, market_key TEXT NOT NULL, platform TEXT NOT NULL,
      market_id TEXT NOT NULL, opened_ts TEXT NOT NULL, side TEXT NOT NULL, entry_price REAL NOT NULL,
      contracts REAL NOT NULL, model_probability REAL, net_edge REAL, cost_per_contract REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'OPEN', result TEXT, settled_ts TEXT, pnl REAL,
      UNIQUE(market_key,market_id))""")
    _ensure_columns(con,"market_trades",TRADE_COLUMNS)
    con.execute("CREATE INDEX IF NOT EXISTS idx_market_trades_key_status ON market_trades(market_key,status)")
    con.execute("""CREATE TABLE IF NOT EXISTS price_ticks(
      ts REAL PRIMARY KEY, price REAL NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_price_ticks_ts ON price_ticks(ts)")
    con.execute("""CREATE TABLE IF NOT EXISTS market_state(
      market_key TEXT PRIMARY KEY,current_market_id TEXT,skipped_rounds INTEGER NOT NULL DEFAULT 0,updated_ts TEXT)""")
    _ensure_columns(con,"market_state",STATE_COLUMNS)
    con.execute("""CREATE TABLE IF NOT EXISTS round_activity(
      market_key TEXT NOT NULL, market_id TEXT NOT NULL, low_vol INTEGER NOT NULL DEFAULT 0,
      traded INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
      first_seen_ts TEXT, updated_ts TEXT, PRIMARY KEY(market_key,market_id))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_round_activity_market ON round_activity(market_key,completed,low_vol)")
    con.commit(); return con

def log_market_snapshot(**kw):
    cols=["ts","market_key","platform","timeframe","market_id","seconds_left","target","target_quality","reference","reference_source","yes_bid","yes_ask","no_bid","no_ask","p_yes","action","net_edge","reason","chart_read","chart_score","locked","adaptive","skipped_rounds","threshold_mode","strategy_type","pair_cost","maker_pair_cost","maker_pair_edge","book_imbalance","watch_side","confirmation_count","confirmation_required"]
    con=connect(); con.execute("INSERT INTO market_snapshots("+",".join(cols)+") VALUES("+",".join(["?"]*len(cols))+")",[kw.get(c) for c in cols]); con.commit(); con.close()

def register_market_round(market_key, market_id):
    now=datetime.now(timezone.utc).isoformat(); con=connect(); row=con.execute("SELECT * FROM market_state WHERE market_key=?",(market_key,)).fetchone()
    if row is None:
        con.execute("INSERT INTO market_state(market_key,current_market_id,skipped_rounds,updated_ts) VALUES(?,?,0,?)",(market_key,market_id,now)); con.commit(); con.close(); return 0
    skipped=int(row['skipped_rounds'] or 0); prior=row['current_market_id']
    if prior and prior!=market_id:
        trade_row=con.execute("SELECT 1 FROM market_trades WHERE market_key=? AND market_id=? LIMIT 1",(market_key,prior)).fetchone()
        activity_row=con.execute("SELECT traded FROM round_activity WHERE market_key=? AND market_id=?",(market_key,prior)).fetchone()
        traded=bool(trade_row) or bool(activity_row and int(activity_row['traded'] or 0))
        skipped=0 if traded else skipped+1
        con.execute("UPDATE round_activity SET traded=?,completed=1,updated_ts=? WHERE market_key=? AND market_id=?",(1 if traded else 0,now,market_key,prior))
        con.execute("UPDATE market_state SET current_market_id=?,skipped_rounds=?,updated_ts=?,candidate_side=NULL,candidate_count=0,candidate_updated_ts=NULL WHERE market_key=?",(market_id,skipped,now,market_key)); con.commit()
    elif not prior:
        con.execute("UPDATE market_state SET current_market_id=?,updated_ts=? WHERE market_key=?",(market_id,now,market_key)); con.commit()
    con.close(); return skipped


def update_round_activity(market_key, market_id, low_vol=None, traded=None):
    now=datetime.now(timezone.utc).isoformat(); con=connect()
    try:
        row=con.execute("SELECT * FROM round_activity WHERE market_key=? AND market_id=?",(market_key,market_id)).fetchone()
        if row is None:
            con.execute("INSERT INTO round_activity(market_key,market_id,low_vol,traded,completed,first_seen_ts,updated_ts) VALUES(?,?,?,?,0,?,?)",
                        (market_key,market_id,1 if low_vol else 0,1 if traded else 0,now,now))
        else:
            lv=int(row['low_vol']) if low_vol is None else (1 if low_vol else 0)
            tr=int(row['traded']) if traded is None else (1 if traded else 0)
            con.execute("UPDATE round_activity SET low_vol=?,traded=?,updated_ts=? WHERE market_key=? AND market_id=?",(lv,tr,now,market_key,market_id))
        con.commit()
    finally:
        con.close()

def low_vol_activity_state(market_key, window_rounds=10):
    """Return rolling activity over the most recent completed low-vol rounds."""
    con=connect()
    try:
        rows=con.execute("SELECT market_id,traded FROM round_activity WHERE market_key=? AND completed=1 AND low_vol=1 ORDER BY updated_ts DESC LIMIT ?",
                         (market_key,max(1,int(window_rounds)))).fetchall()
    finally:
        con.close()
    rounds=len(rows); traded=sum(int(r['traded'] or 0) for r in rows); skips=rounds-traded
    return {"rounds":rounds,"traded":traded,"skips":skips,"trade_rate":(traded/rounds if rounds else 0.0)}

def mark_round_traded(market_key, market_id):
    update_round_activity(market_key, market_id, traded=True)

def skipped_rounds(market_key):
    con=connect(); row=con.execute("SELECT skipped_rounds FROM market_state WHERE market_key=?",(market_key,)).fetchone(); con.close(); return int(row[0]) if row else 0

def has_market_trade(market_key,market_id):
    con=connect(); r=con.execute("SELECT 1 FROM market_trades WHERE market_key=? AND market_id=?",(market_key,market_id)).fetchone(); con.close(); return bool(r)

def get_open_market_trade(market_key,market_id):
    con=connect(); r=con.execute("SELECT * FROM market_trades WHERE market_key=? AND market_id=? AND status='OPEN'",(market_key,market_id)).fetchone(); con.close(); return dict(r) if r else None

def open_market_trade(market_key,platform,market_id,side,entry_price,contracts,model_probability,net_edge,cost_per_contract=0.0,hedged=0,hedge_side=None,hedge_price=None,hedge_cost_per_contract=0.0,strategy_type='DIRECTIONAL'):
    con=connect()
    try:
      con.execute("""INSERT OR IGNORE INTO market_trades(market_key,platform,market_id,opened_ts,side,entry_price,contracts,model_probability,net_edge,cost_per_contract,status,hedged,hedge_side,hedge_price,hedge_cost_per_contract,strategy_type) VALUES(?,?,?,?,?,?,?,?,?,?, 'OPEN',?,?,?,?,?)""",
        (market_key,platform,market_id,datetime.now(timezone.utc).isoformat(),side,float(entry_price),float(contracts),float(model_probability),float(net_edge),float(cost_per_contract or 0),int(hedged),hedge_side,None if hedge_price is None else float(hedge_price),float(hedge_cost_per_contract or 0),strategy_type))
      con.commit()
    finally: con.close()

def hedge_trade(market_key,market_id,hedge_side,hedge_price,hedge_cost_per_contract=0.0,strategy_type='HEDGE_LOCK'):
    con=connect(); con.execute("UPDATE market_trades SET hedged=1,hedge_side=?,hedge_price=?,hedge_cost_per_contract=?,strategy_type=? WHERE market_key=? AND market_id=? AND status='OPEN'",(hedge_side,float(hedge_price),float(hedge_cost_per_contract or 0),strategy_type,market_key,market_id)); con.commit(); con.close()

def settle_market_trade(market_key,market_id,result):
    result=str(result).upper();
    if result not in ('YES','NO'): return None
    con=connect(); row=con.execute("SELECT * FROM market_trades WHERE market_key=? AND market_id=? AND status='OPEN'",(market_key,market_id)).fetchone()
    if not row: con.close(); return None
    c=float(row['contracts']); price=float(row['entry_price']); cost=float(row['cost_per_contract'] or 0)
    if str(row['side']).upper()=='PAIR' or int(row['hedged'] or 0):
        hp=float(row['hedge_price'] or 0); hcost=float(row['hedge_cost_per_contract'] or 0)
        gross=c*(1.0-price-hp); pnl=gross-c*(cost+hcost); won=pnl>0
    else:
        won=result==str(row['side']).upper(); gross=c*((1.0-price) if won else -price); pnl=gross-c*cost
    con.execute("UPDATE market_trades SET status='SETTLED',result=?,settled_ts=?,pnl=? WHERE id=?",(result,datetime.now(timezone.utc).isoformat(),pnl,row['id'])); con.commit(); con.close()
    return {'id':row['id'],'market_key':market_key,'market_id':market_id,'result':result,'pnl':pnl,'won':won}


def observe_candidate(market_key, market_id, side, max_gap_seconds=10):
    """Persist a pre-trade candidate. Returns consecutive confirmation count."""
    side=str(side or "").upper()
    if side not in ("YES","NO"):
        return 0
    now=datetime.now(timezone.utc)
    con=connect()
    try:
        row=con.execute("SELECT * FROM market_state WHERE market_key=?",(market_key,)).fetchone()
        if row is None:
            con.execute("INSERT INTO market_state(market_key,current_market_id,skipped_rounds,updated_ts,candidate_side,candidate_count,candidate_updated_ts) VALUES(?,?,0,?,?,1,?)",(market_key,market_id,now.isoformat(),side,now.isoformat()))
            con.commit(); return 1
        count=int(row['candidate_count'] or 0)
        prior_side=str(row['candidate_side'] or '').upper()
        prior_market=row['current_market_id']
        fresh=False
        try:
            prev=datetime.fromisoformat(str(row['candidate_updated_ts']).replace('Z','+00:00')) if row['candidate_updated_ts'] else None
            fresh=bool(prev and (now-prev).total_seconds() <= float(max_gap_seconds))
        except Exception:
            fresh=False
        if prior_market==market_id and prior_side==side and fresh:
            count+=1
        else:
            count=1
        con.execute("UPDATE market_state SET current_market_id=?,candidate_side=?,candidate_count=?,candidate_updated_ts=?,updated_ts=? WHERE market_key=?",(market_id,side,count,now.isoformat(),now.isoformat(),market_key))
        con.commit(); return count
    finally:
        con.close()

def candidate_state(market_key):
    con=connect(); row=con.execute("SELECT candidate_side,candidate_count,candidate_updated_ts FROM market_state WHERE market_key=?",(market_key,)).fetchone(); con.close()
    return dict(row) if row else {'candidate_side':None,'candidate_count':0,'candidate_updated_ts':None}

def clear_candidate(market_key):
    con=connect(); con.execute("UPDATE market_state SET candidate_side=NULL,candidate_count=0,candidate_updated_ts=NULL WHERE market_key=?",(market_key,)); con.commit(); con.close()




def record_price_tick(ts, price, keep_seconds=900):
    """Store a lightweight BTC spot sample used for TWAP-style local proxies."""
    try:
        ts=float(ts); price=float(price)
    except Exception:
        return
    con=connect()
    try:
        con.execute("INSERT OR REPLACE INTO price_ticks(ts,price) VALUES(?,?)",(ts,price))
        con.execute("DELETE FROM price_ticks WHERE ts<?",(ts-float(keep_seconds),))
        con.commit()
    finally:
        con.close()


def _tick_rows(start_ts, end_ts):
    con=connect()
    try:
        rows=con.execute(
            "SELECT ts,price FROM price_ticks WHERE ts>=? AND ts<=? ORDER BY ts ASC",
            (float(start_ts)-5.0,float(end_ts)+1.0)
        ).fetchall()
        return [(float(r['ts']),float(r['price'])) for r in rows]
    finally:
        con.close()


def tick_twap(end_ts, window_seconds=60, min_points=8, max_edge_gap=8.0):
    """Time-weighted local BTC proxy over [end-window, end).

    Samples are normally about 2 seconds apart. The function returns None when
    coverage is too sparse, avoiding a false sense of precision after startup.
    """
    end=float(end_ts); start=end-float(window_seconds)
    rows=_tick_rows(start,end)
    rows=[(t,p) for t,p in rows if t < end]
    if len(rows) < int(min_points):
        return None
    # Find first sample close enough to the start; if one is slightly before the
    # window, carry it forward. Otherwise require a reasonably small initial gap.
    before=[(t,p) for t,p in rows if t<=start]
    inside=[(t,p) for t,p in rows if t>start]
    if before:
        current_t=start; current_p=before[-1][1]
    elif inside and inside[0][0]-start <= float(max_edge_gap):
        current_t=start; current_p=inside[0][1]
    else:
        return None
    area=0.0
    points=inside if before else inside[1:]
    for t,p in points:
        if t<=current_t: continue
        seg_end=min(t,end)
        area += current_p*(seg_end-current_t)
        current_t=seg_end; current_p=p
        if current_t>=end: break
    if end-current_t > float(max_edge_gap):
        return None
    if current_t<end:
        area += current_p*(end-current_t)
    return area/max(float(window_seconds),1e-9)


def settlement_twap_projection(end_ts, current_ts, current_price, window_seconds=60, min_elapsed=10):
    """Project the final settlement-minute TWAP using observed ticks + flat future.

    This is only a proxy. It becomes useful once the final 60-second settlement
    window has started. The unknown remainder is conservatively held at current
    spot rather than extrapolated with momentum.
    """
    end=float(end_ts); now=min(float(current_ts),end); start=end-float(window_seconds)
    if now <= start + float(min_elapsed):
        return None
    observed=tick_twap(now, window_seconds=now-start, min_points=max(4,int((now-start)/6)), max_edge_gap=8.0)
    if observed is None:
        return None
    elapsed=now-start; remaining=max(0.0,end-now)
    projected=(observed*elapsed + float(current_price)*remaining)/float(window_seconds)
    return projected


def recent_quote_momentum(market_key, market_id, current_bid=None, current_ask=None, lookback=5):
    """YES-mid change over recent snapshots, in probability-price units.

    Positive means the market quote has moved toward UP. This uses quote changes
    rather than inferred trade direction, which is intentionally avoided.
    """
    try:
        if current_bid is None or current_ask is None:
            return None
        current_mid=(float(current_bid)+float(current_ask))/2.0
    except Exception:
        return None
    con=connect()
    try:
        rows=con.execute(
            "SELECT yes_bid,yes_ask FROM market_snapshots WHERE market_key=? AND market_id=? AND yes_bid IS NOT NULL AND yes_ask IS NOT NULL ORDER BY id DESC LIMIT ?",
            (market_key,market_id,max(1,int(lookback)))
        ).fetchall()
    finally:
        con.close()
    mids=[]
    for r in reversed(rows):
        try: mids.append((float(r['yes_bid'])+float(r['yes_ask']))/2.0)
        except Exception: pass
    if not mids:
        return 0.0
    return current_mid-mids[0]

def open_trades():
    con=connect(); rows=con.execute("SELECT * FROM market_trades WHERE status='OPEN' ORDER BY id").fetchall(); con.close(); return [dict(r) for r in rows]

def open_exposure():
    con=connect(); rows=con.execute("SELECT * FROM market_trades WHERE status='OPEN'").fetchall(); con.close(); total=0.0
    for r in rows:
        total += float(r['contracts'] or 0)*float(r['entry_price'] or 0)
        if int(r['hedged'] or 0) or str(r['side']).upper()=='PAIR': total += float(r['contracts'] or 0)*float(r['hedge_price'] or 0)
    return total

def daily_realized_pnl():
    start=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(); con=connect(); r=con.execute("SELECT COALESCE(SUM(pnl),0) FROM market_trades WHERE status='SETTLED' AND settled_ts>=?",(start,)).fetchone(); con.close(); return float(r[0] or 0)

def market_stats(market_key=None,starting_bankroll=1000.0):
    con=connect()
    try:
        rows=con.execute("SELECT * FROM market_trades WHERE "+("market_key=? AND " if market_key else "")+"status='SETTLED' ORDER BY id",((market_key,) if market_key else ())).fetchall()
        if market_key:
            rounds=int(con.execute("SELECT COUNT(DISTINCT market_id) FROM market_snapshots WHERE market_key=? AND market_id IS NOT NULL",(market_key,)).fetchone()[0] or 0)
            traded=int(con.execute("SELECT COUNT(*) FROM market_trades WHERE market_key=?",(market_key,)).fetchone()[0] or 0)
        else:
            rounds=int(con.execute("SELECT COUNT(DISTINCT market_key||':'||market_id) FROM market_snapshots WHERE market_id IS NOT NULL").fetchone()[0] or 0)
            traded=int(con.execute("SELECT COUNT(*) FROM market_trades").fetchone()[0] or 0)
    finally:
        con.close()
    wins=[float(r['pnl'] or 0)>0 for r in rows]; pnl=sum(float(r['pnl'] or 0) for r in rows); cur=0
    for w in reversed(wins):
        if w: cur+=1
        else: break
    best=run=0
    for w in wins: run=run+1 if w else 0; best=max(best,run)
    return {'settled':len(rows),'wins':sum(wins),'losses':len(rows)-sum(wins),'win_rate':sum(wins)/len(rows) if rows else 0.0,'current_streak':cur,'best_streak':best,'pnl':pnl,'bankroll':float(starting_bankroll)+pnl,'rounds_observed':rounds,'rounds_traded':traded,'trade_frequency':(traded/rounds if rounds else 0.0)}

def latest_win_id():
    con=connect(); r=con.execute("SELECT MAX(id) AS id FROM market_trades WHERE status='SETTLED' AND pnl>0").fetchone(); con.close(); return int(r['id'] or 0)
