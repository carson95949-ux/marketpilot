from __future__ import annotations
import hashlib, os, re, secrets, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

ROOT=Path(__file__).resolve().parent
DATA_DIR=Path(os.getenv('MARKETPILOT_DATA_DIR',str(ROOT))); DATA_DIR.mkdir(parents=True,exist_ok=True)
DB=DATA_DIR/'access.sqlite3'
USER_COLUMNS={'leaderboard_name':'TEXT','leaderboard_opt_in':'INTEGER NOT NULL DEFAULT 0'}

def _ensure_columns(con,table,columns):
    existing={r[1] for r in con.execute(f'PRAGMA table_info({table})').fetchall()}
    for name,ddl in columns.items():
        if name not in existing: con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')

def _now(): return datetime.now(timezone.utc)
def _hash(token): return hashlib.sha256(token.encode()).hexdigest()
def _clean_email(email):
    email=str(email or '').strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise ValueError('Enter a valid email address.')
    return email

def connect():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,
      created_at TEXT NOT NULL,trial_started_at TEXT,trial_expires_at TEXT,purchased INTEGER NOT NULL DEFAULT 0,
      purchased_at TEXT,stripe_session_id TEXT UNIQUE,stripe_customer_id TEXT)''')
    _ensure_columns(con,'users',USER_COLUMNS)
    con.execute('''CREATE TABLE IF NOT EXISTS access_tokens(
      id INTEGER PRIMARY KEY AUTOINCREMENT,token_hash TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,email TEXT,
      created_at TEXT NOT NULL,expires_at TEXT,stripe_session_id TEXT UNIQUE,active INTEGER NOT NULL DEFAULT 1)''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_access_tokens_hash ON access_tokens(token_hash)'); con.commit(); return con

def create_user(email,password):
    email=_clean_email(email); password=str(password or '')
    if len(password)<8: raise ValueError('Password must be at least 8 characters.')
    con=connect()
    try:
        cur=con.execute('INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)',(email,generate_password_hash(password),_now().isoformat())); con.commit(); uid=cur.lastrowid
    except sqlite3.IntegrityError: raise ValueError('An account with that email already exists.')
    finally: con.close()
    return get_user(uid)

def authenticate_user(email,password):
    try: email=_clean_email(email)
    except ValueError: return None
    con=connect(); row=con.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); con.close()
    return dict(row) if row and check_password_hash(row['password_hash'],str(password or '')) else None

def get_user(user_id):
    if not user_id: return None
    con=connect(); row=con.execute('SELECT * FROM users WHERE id=?',(int(user_id),)).fetchone(); con.close(); return dict(row) if row else None

def start_trial_for_user(user_id,minutes=30):
    user=get_user(user_id)
    if not user: raise ValueError('Account not found.')
    if int(user.get('purchased') or 0): return access_for_user(user_id) or {'id':user_id,'kind':'purchase'}
    if user.get('trial_started_at'): return access_for_user(user_id) or {'id':user_id,'kind':'expired'}
    now=_now(); expiry=now+timedelta(minutes=max(1,int(minutes))); con=connect(); con.execute('UPDATE users SET trial_started_at=?,trial_expires_at=? WHERE id=?',(now.isoformat(),expiry.isoformat(),int(user_id))); con.commit(); con.close(); return access_for_user(user_id)

def mark_purchase_for_user(user_id,stripe_session_id=None,stripe_customer_id=None):
    con=connect(); con.execute('UPDATE users SET purchased=1,purchased_at=?,stripe_session_id=COALESCE(?,stripe_session_id),stripe_customer_id=COALESCE(?,stripe_customer_id) WHERE id=?',(_now().isoformat(),stripe_session_id,stripe_customer_id,int(user_id))); con.commit(); con.close(); return get_user(user_id)

def access_for_user(user_id):
    user=get_user(user_id)
    if not user:return None
    if int(user.get('purchased') or 0): return {'id':user['id'],'kind':'purchase','email':user['email'],'remaining_seconds':None}
    if user.get('trial_expires_at'):
        try: rem=int((datetime.fromisoformat(str(user['trial_expires_at']).replace('Z','+00:00'))-_now()).total_seconds())
        except Exception: rem=0
        if rem>0:return {'id':user['id'],'kind':'trial','email':user['email'],'remaining_seconds':rem}
    return None

def trial_status_for_user(user_id):
    user=get_user(user_id)
    if not user:return {'started':False,'active':False,'expired':False,'remaining_seconds':0}
    access=access_for_user(user_id); started=bool(user.get('trial_started_at')); active=bool(access and access['kind']=='trial')
    return {'started':started,'active':active,'expired':started and not active and not int(user.get('purchased') or 0),'remaining_seconds':int(access.get('remaining_seconds') or 0) if access else 0,'expires_at':user.get('trial_expires_at')}

# Legacy cookie-token compatibility
def create_trial(minutes=30):
    token=secrets.token_urlsafe(32); now=_now(); expiry=now+timedelta(minutes=max(1,int(minutes))); con=connect(); con.execute('INSERT INTO access_tokens(token_hash,kind,created_at,expires_at,active) VALUES(?,?,?,?,1)',(_hash(token),'trial',now.isoformat(),expiry.isoformat())); con.commit(); con.close(); return token,expiry

def create_purchase(email=None,stripe_session_id=None):
    token=secrets.token_urlsafe(32); con=connect(); con.execute('INSERT INTO access_tokens(token_hash,kind,email,created_at,expires_at,stripe_session_id,active) VALUES(?,?,?,?,?,?,1)',(_hash(token),'purchase',email,_now().isoformat(),None,stripe_session_id)); con.commit(); con.close(); return token

def verify(token):
    if not token:return None
    con=connect(); row=con.execute('SELECT * FROM access_tokens WHERE token_hash=? AND active=1',(_hash(token),)).fetchone(); con.close()
    if not row:return None
    item=dict(row)
    if item['kind']=='trial' and item.get('expires_at'):
        try: rem=int((datetime.fromisoformat(item['expires_at'].replace('Z','+00:00'))-_now()).total_seconds())
        except Exception:return None
        if rem<=0:return None
        item['remaining_seconds']=rem
    else:item['remaining_seconds']=None
    return item

def revoke(token):
    if not token:return
    con=connect(); con.execute('UPDATE access_tokens SET active=0 WHERE token_hash=?',(_hash(token),)); con.commit(); con.close()


def update_leaderboard_profile(user_id,name,opt_in):
    name=str(name or '').strip()
    if name and not re.fullmatch(r'[A-Za-z0-9 _.-]{3,20}',name):
        raise ValueError('Public name must be 3–20 characters using letters, numbers, spaces, _, . or -.')
    con=connect(); con.execute('UPDATE users SET leaderboard_name=?,leaderboard_opt_in=? WHERE id=?',(name or None,1 if opt_in else 0,int(user_id))); con.commit(); con.close(); return get_user(user_id)

def leaderboard_users():
    con=connect(); rows=con.execute('SELECT id,email,created_at,trial_started_at,leaderboard_name,leaderboard_opt_in FROM users ORDER BY created_at').fetchall(); con.close(); return [dict(r) for r in rows]
