from __future__ import annotations
import base64, hashlib, hmac, json, os, re, sqlite3, time, uuid
from datetime import datetime, timezone
from pathlib import Path
import requests
from cryptography.fernet import Fernet
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent; load_dotenv(ROOT/'.env')
DATA_DIR=Path(os.getenv('MARKETPILOT_DATA_DIR',str(ROOT))); DATA_DIR.mkdir(parents=True,exist_ok=True)
DB=DATA_DIR/'connections.sqlite3'; RELAYER='https://relayer-v2.polymarket.com'
ADDRESS_RE=re.compile(r'^0x[0-9a-fA-F]{40}$'); KEY_RE=re.compile(r'^0x[0-9a-fA-F]{64}$'); HEX_RE=re.compile(r'^0x[0-9a-fA-F]+$')
def _now_iso():return datetime.now(timezone.utc).isoformat()
def _address(v):
    v=str(v or '').strip()
    if not ADDRESS_RE.fullmatch(v):raise ValueError('Invalid EVM address.')
    return v
def _fernet():
    explicit=os.getenv('SESSION_ENCRYPTION_KEY','').strip(); key=explicit.encode() if explicit else base64.urlsafe_b64encode(hashlib.sha256(os.getenv('MARKETPILOT_SECRET_KEY','dev-change-me-before-deploy').encode()).digest()); return Fernet(key)
def _encrypt(v):return _fernet().encrypt(v.encode()).decode()
def _decrypt(v):return _fernet().decrypt(v.encode()).decode()
def connect_db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; con.execute('''CREATE TABLE IF NOT EXISTS polymarket_connections(id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER NOT NULL UNIQUE,owner_address TEXT NOT NULL,deposit_wallet TEXT NOT NULL,session_address TEXT NOT NULL,encrypted_session_key TEXT NOT NULL,valid_until INTEGER NOT NULL,state TEXT NOT NULL,nonce TEXT,deadline INTEGER,calldata TEXT,transaction_id TEXT,transaction_hash TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,revoked_at TEXT)'''); con.commit(); return con
def builder_configured():return all(os.getenv(k,'').strip() for k in ('POLYMARKET_BUILDER_API_KEY','POLYMARKET_BUILDER_SECRET','POLYMARKET_BUILDER_PASSPHRASE'))
def _fetch_wallet_nonce(owner):
    r=requests.get(RELAYER+'/v1/account/transactions/params',params={'address':owner,'type':'WALLET'},timeout=12); r.raise_for_status(); n=r.json().get('nonce')
    if n is None:raise RuntimeError('Polymarket relayer did not return a wallet nonce.')
    return str(n)
def _typed_data(wallet,nonce,deadline,calldata):return {'domain':{'name':'DepositWallet','version':'1','chainId':137,'verifyingContract':wallet},'types':{'Call':[{'name':'target','type':'address'},{'name':'value','type':'uint256'},{'name':'data','type':'bytes'}],'Batch':[{'name':'wallet','type':'address'},{'name':'nonce','type':'uint256'},{'name':'deadline','type':'uint256'},{'name':'calls','type':'Call[]'}]},'primaryType':'Batch','message':{'wallet':wallet,'nonce':str(nonce),'deadline':str(int(deadline)),'calls':[{'target':wallet,'value':'0','data':calldata}]}}
def _validate_calldata(c,minb,maxb):
    c=str(c or '').strip(); size=(len(c)-2)//2 if c.startswith('0x') else -1
    if not HEX_RE.fullmatch(c) or len(c)%2 or size<minb or size>maxb:raise ValueError('Invalid wallet authorization data.')
    return c
def _builder_headers(path,body):
    if not builder_configured():raise RuntimeError('MarketPilot owner has not configured Polymarket Builder credentials yet.')
    ts=str(int(time.time())); st=os.environ['POLYMARKET_BUILDER_SECRET'].strip(); padded=st+'='*((4-len(st)%4)%4)
    try:secret=base64.urlsafe_b64decode(padded)
    except Exception:secret=base64.b64decode(padded)
    sig=base64.urlsafe_b64encode(hmac.new(secret,(ts+'POST'+path+body).encode(),hashlib.sha256).digest()).decode()
    return {'Content-Type':'application/json','POLY_BUILDER_API_KEY':os.environ['POLYMARKET_BUILDER_API_KEY'].strip(),'POLY_BUILDER_TIMESTAMP':ts,'POLY_BUILDER_PASSPHRASE':os.environ['POLYMARKET_BUILDER_PASSPHRASE'].strip(),'POLY_BUILDER_SIGNATURE':sig,'Idempotency-Key':str(uuid.uuid4())}
def _public(row):
    if not row:return None
    d=dict(row)
    for k in ('encrypted_session_key','nonce','calldata'):d.pop(k,None)
    return d
def get_connection(account_id):
    con=connect_db(); row=con.execute('SELECT * FROM polymarket_connections WHERE account_id=?',(int(account_id),)).fetchone(); con.close(); return _public(row)
def _get_raw(account_id):
    con=connect_db(); row=con.execute('SELECT * FROM polymarket_connections WHERE account_id=?',(int(account_id),)).fetchone(); con.close(); return row
def start_authorization(account_id,owner_address,deposit_wallet,session_address,session_private_key,calldata,valid_until):
    owner=_address(owner_address); wallet=_address(deposit_wallet); sess=_address(session_address); key=str(session_private_key or '').strip()
    if not KEY_RE.fullmatch(key):raise ValueError('Session key generation failed. Refresh and try again.')
    calldata=_validate_calldata(calldata,68,68); now=int(time.time()); valid_until=int(valid_until)
    if valid_until<now+3600 or valid_until>now+181*24*3600:raise ValueError('Session authorization expiry is outside the allowed range.')
    body=calldata[10:]
    if len(body)!=128 or body[:64][-40:].lower()!=sess[2:].lower() or int(body[64:128],16)!=valid_until:raise ValueError('Authorization payload does not match the generated session signer.')
    nonce=_fetch_wallet_nonce(owner); deadline=now+180; typed=_typed_data(wallet,nonce,deadline,calldata); con=connect_db(); con.execute('''INSERT INTO polymarket_connections(account_id,owner_address,deposit_wallet,session_address,encrypted_session_key,valid_until,state,nonce,deadline,calldata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET owner_address=excluded.owner_address,deposit_wallet=excluded.deposit_wallet,session_address=excluded.session_address,encrypted_session_key=excluded.encrypted_session_key,valid_until=excluded.valid_until,state=excluded.state,nonce=excluded.nonce,deadline=excluded.deadline,calldata=excluded.calldata,transaction_id=NULL,transaction_hash=NULL,last_error=NULL,revoked_at=NULL,updated_at=excluded.updated_at''',(int(account_id),owner,wallet,sess,_encrypt(key),valid_until,'AWAITING_SIGNATURE',nonce,deadline,calldata,_now_iso(),_now_iso())); con.commit(); con.close(); return {'owner_address':owner,'deposit_wallet':wallet,'session_address':sess,'valid_until':valid_until,'typed_data':typed,'state':'AWAITING_SIGNATURE'}
def submit_authorization(account_id,signature):
    row=_get_raw(account_id)
    if not row or row['state']!='AWAITING_SIGNATURE':raise RuntimeError('No authorization is awaiting a wallet signature.')
    signature=str(signature or '').strip()
    if not signature.startswith('0x') or len(signature)<100:raise ValueError('Wallet signature is missing or invalid.')
    payload={'walletAddress':row['deposit_wallet'],'sessionSignerAddress':row['session_address'],'scopes':['CLOB'],'validUntil':str(row['valid_until']),'nonce':str(row['nonce']),'deadline':str(row['deadline']),'signature':signature}; body=json.dumps(payload,separators=(',',':')); path='/v1/session-signers/authorizations'; r=requests.post(RELAYER+path,data=body,headers=_builder_headers(path,body),timeout=20)
    if r.status_code>=400:raise RuntimeError(f'Polymarket authorization failed ({r.status_code}): {r.text[:400]}')
    data=r.json(); txid=data.get('transactionId') or data.get('transaction_id')
    if not txid:raise RuntimeError('Polymarket relayer returned no transaction ID.')
    con=connect_db(); con.execute('UPDATE polymarket_connections SET state=?,transaction_id=?,transaction_hash=?,last_error=NULL,updated_at=? WHERE account_id=?',('SUBMITTED',txid,data.get('transactionHash') or data.get('transaction_hash'),_now_iso(),int(account_id))); con.commit(); con.close(); return {'state':'SUBMITTED','transaction_id':txid}
def start_revocation(account_id,calldata):
    row=_get_raw(account_id)
    if not row or row['state'] not in ('ACTIVE','SUBMITTED'):raise RuntimeError('There is no active Polymarket session to revoke.')
    calldata=_validate_calldata(calldata,36,36); body=calldata[10:]
    if len(body)!=64 or body[-40:].lower()!=row['session_address'][2:].lower():raise ValueError('Revocation payload does not match the connected session signer.')
    nonce=_fetch_wallet_nonce(row['owner_address']); deadline=int(time.time())+180; typed=_typed_data(row['deposit_wallet'],nonce,deadline,calldata); con=connect_db(); con.execute('UPDATE polymarket_connections SET state=?,nonce=?,deadline=?,calldata=?,transaction_id=NULL,last_error=NULL,updated_at=? WHERE account_id=?',('AWAITING_REVOKE_SIGNATURE',nonce,deadline,calldata,_now_iso(),int(account_id))); con.commit(); con.close(); return {'typed_data':typed,'state':'AWAITING_REVOKE_SIGNATURE','session_address':row['session_address']}
def submit_revocation(account_id,signature):
    row=_get_raw(account_id)
    if not row or row['state']!='AWAITING_REVOKE_SIGNATURE':raise RuntimeError('No revocation is awaiting a wallet signature.')
    signature=str(signature or '').strip()
    if not signature.startswith('0x') or len(signature)<100:raise ValueError('Wallet signature is missing or invalid.')
    payload={'walletAddress':row['deposit_wallet'],'sessionSignerAddress':row['session_address'],'nonce':str(row['nonce']),'deadline':str(row['deadline']),'signature':signature}; body=json.dumps(payload,separators=(',',':')); path='/v1/session-signers/revocations'; r=requests.post(RELAYER+path,data=body,headers=_builder_headers(path,body),timeout=20)
    if r.status_code>=400:raise RuntimeError(f'Polymarket revocation failed ({r.status_code}): {r.text[:400]}')
    data=r.json(); txid=data.get('transactionId') or data.get('transaction_id')
    if not txid:raise RuntimeError('Polymarket relayer returned no revocation transaction ID.')
    con=connect_db(); con.execute('UPDATE polymarket_connections SET state=?,transaction_id=?,transaction_hash=?,last_error=NULL,updated_at=? WHERE account_id=?',('REVOKING',txid,data.get('transactionHash') or data.get('transaction_hash'),_now_iso(),int(account_id))); con.commit(); con.close(); return {'state':'REVOKING','transaction_id':txid}
def refresh_status(account_id):
    row=_get_raw(account_id)
    if not row:return None
    if row['state'] in ('SUBMITTED','REVOKING') and row['transaction_id']:
        try:
            r=requests.get(RELAYER+f"/v1/account/transactions/{row['transaction_id']}",timeout=12); r.raise_for_status(); data=r.json(); st=str(data.get('state') or data.get('status') or '').upper(); txh=data.get('transaction_hash') or data.get('transactionHash') or row['transaction_hash']
            if st=='STATE_CONFIRMED':
                ns='ACTIVE' if row['state']=='SUBMITTED' else 'REVOKED'; rv=_now_iso() if ns=='REVOKED' else None; con=connect_db(); con.execute('UPDATE polymarket_connections SET state=?,transaction_hash=?,revoked_at=COALESCE(?,revoked_at),last_error=NULL,updated_at=? WHERE account_id=?',(ns,txh,rv,_now_iso(),int(account_id))); con.commit(); con.close()
            elif st in ('STATE_FAILED','STATE_INVALID'):
                con=connect_db(); con.execute('UPDATE polymarket_connections SET state=?,last_error=?,updated_at=? WHERE account_id=?',('FAILED',str(data.get('error_msg') or st),_now_iso(),int(account_id))); con.commit(); con.close()
        except Exception as exc:
            con=connect_db(); con.execute('UPDATE polymarket_connections SET last_error=?,updated_at=? WHERE account_id=?',(str(exc)[:500],_now_iso(),int(account_id))); con.commit(); con.close()
    return get_connection(account_id)
def get_session_credentials(account_id):
    row=_get_raw(account_id)
    if not row or row['state']!='ACTIVE':raise RuntimeError('Polymarket session is not active.')
    return {'owner_address':row['owner_address'],'wallet':row['deposit_wallet'],'session_address':row['session_address'],'private_key':_decrypt(row['encrypted_session_key']),'valid_until':int(row['valid_until'])}
