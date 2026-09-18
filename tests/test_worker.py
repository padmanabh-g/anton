import asyncio
import json
import time
from test_core import db, alert
from anton.worker import Worker
from anton.providers import UnknownOutcome, NotReady

class Fake:
    def __init__(self):self.calls=[];self.sessions=[];self.messages=[];self.ready=False
    async def call(self,i,purpose):
        self.calls.append(purpose);return {'conversation_id':'c','call_sid':'sid','purpose':purpose}
    async def telegram(self,text,buttons=None):self.messages.append(text);return {'message_id':1}
    async def dispatch(self,i,rollback=False):self.sessions.append(i['id']);return {'session_id':'s','session_url':'https://app.devin.ai/s'}
    async def session(self,id):return {'status_enum':'finished','pull_request':{'url':'https://github.com/padmanabh-g/anton-demo-product/pull/1'}}
    def pr_number(self,url):return 1
    async def verify_pr(self,i,number):
        if not self.ready:raise NotReady('Checks pending')
        return {'head':'c'*40,'url':'https://github.com/padmanabh-g/anton-demo-product/pull/1','number':1,'checks':[]}

async def drain(w):
    while a:=w.db.claim():await w.execute(a)

def dispatch(db):
    i=alert(db);p=db.propose(i['id'],'dispatch_fix','42','telegram');db.approve(p['token'],'42','telegram');return i

def test_restart_polling_and_exactly_one_callback(db):
    i=dispatch(db);p=Fake();w=Worker(db,p);asyncio.run(drain(w))
    assert len(p.sessions)==1
    asyncio.run(Worker(db,p).poll(db.incident(i['id'])))
    assert db.incident(i['id'])['state']=='verifying_pr'
    assert p.calls==['initial']
    p.ready=True
    asyncio.run(w.poll(db.incident(i['id'])));asyncio.run(w.poll(db.incident(i['id'])));asyncio.run(drain(w))
    assert db.incident(i['id'])['state']=='pr_ready'
    assert p.calls==['initial','result']

def test_timeout_prevents_late_success_until_operator_resume(db):
    i=dispatch(db);p=Fake();w=Worker(db,p);asyncio.run(drain(w))
    db.update_incident(i['id'],deadline=time.time()-1)
    asyncio.run(w.poll(db.incident(i['id'])))
    assert db.incident(i['id'])['state']=='timed_out'
    p.ready=True
    assert db.polling()==[]
    db.resume(i['id'],'operator');asyncio.run(w.poll(db.incident(i['id'])))
    assert db.incident(i['id'])['state']=='pr_ready'

def test_unknown_dispatch_does_not_repeat(db):
    i=dispatch(db);p=Fake()
    async def lose_response(i,rollback=False):raise UnknownOutcome('Response lost')
    p.dispatch=lose_response;w=Worker(db,p);asyncio.run(drain(w));asyncio.run(drain(w))
    assert next(a for a in db.actions(i['id']) if a['kind']=='dispatch_fix')['status']=='unknown'

def test_reset_during_dispatch_preserves_receipt_without_callback(db):
    i=dispatch(db);p=Fake()
    async def reset_inflight(i,rollback=False):
        db.reset('next','operator');return {'session_id':'orphan','session_url':'https://app.devin.ai/orphan'}
    p.dispatch=reset_inflight;asyncio.run(drain(Worker(db,p)))
    a=next(a for a in db.actions(i['id']) if a['kind']=='dispatch_fix')
    assert json.loads(a['result'])['session_id']=='orphan'
    assert db.incident(i['id'])['state']=='cancelled'
    assert db.claim() is None
