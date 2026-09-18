import asyncio
import hashlib
import hmac
import json
import re
import time
from contextlib import asynccontextmanager, suppress
from typing import Literal
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .config import Settings
from .store import Store, Conflict
from .providers import Providers, ProviderFailure
from .worker import Worker

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Alert(Strict):
    event_id:str=Field(min_length=1,max_length=200)
    run_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    monitor_id:str=Field(min_length=1,max_length=200)
    group:str=Field(max_length=500)
    occurrence:str=Field(min_length=1,max_length=200)
    status:Literal['alert','recovered']
    deployed_sha:str=Field(pattern=r'^[0-9a-f]{40}$')
    error_count:int|None=Field(default=None,ge=0)
class Voice(Strict):
    conversation_id:str=Field(min_length=1,max_length=200)
    run_id:str
class Proposal(Voice):action:Literal['dispatch_fix','rollback','page_team']
class Approval(Voice):
    token:str
    confirmed:Literal[True]
class Reset(Strict):run_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
class Retry(Strict):purpose:Literal['initial','result']
class Reconcile(Strict):
    provider_id:str=Field(min_length=1,max_length=200)
    evidence:str=Field(min_length=10,max_length=1000)

def create_app(settings=None):
    s=settings or Settings.from_env();db=Store(s.db_path,s);p=Providers(s);worker=Worker(db,p)
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(worker.run()) if s.worker_enabled.lower()=='true' else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):await task
    app=FastAPI(title='Anton incident commander',version='0.1.0',lifespan=lifespan)
    app.state.db=db;app.state.providers=p
    def secret(value,expected):
        if not expected or not value or not hmac.compare_digest(value,expected):raise HTTPException(401,'Invalid integration credentials')
    async def datadog_auth(r:Request):secret(r.headers.get('x-anton-secret'),s.datadog_secret)
    async def voice_auth(r:Request):secret(r.headers.get('x-anton-secret'),s.voice_secret)
    async def telegram_auth(r:Request):secret(r.headers.get('x-telegram-bot-api-secret-token'),s.telegram_secret)
    async def operator_auth(r:Request):secret(r.headers.get('authorization'),'Bearer '+s.operator_secret if s.operator_secret else '')
    @app.exception_handler(Conflict)
    async def conflict(r,e):return JSONResponse(status_code=409,content={'detail':str(e)})
    @app.exception_handler(ProviderFailure)
    async def provider_error(r,e):return JSONResponse(status_code=503,content={'detail':str(e)})
    @app.get('/health')
    async def health():return {'status':'ok','product':'Anton','scope':'verified remediation PR; no deployment'}
    @app.post('/webhooks/datadog',dependencies=[Depends(datadog_auth)])
    async def datadog(body:Alert):return {'incident':db.ingest(body.model_dump())}
    @app.post('/voice/propose',dependencies=[Depends(voice_auth)])
    async def propose(body:Proposal):
        i=db.voice_context(body.conversation_id,body.run_id)
        if body.action=='rollback':await p.rollback_guard(i)
        return db.propose(i['id'],body.action,s.responder_id,'voice:'+body.conversation_id)
    @app.post('/voice/approve',dependencies=[Depends(voice_auth)])
    async def approve(body:Approval):
        db.voice_context(body.conversation_id,body.run_id)
        return public_action(db.approve(body.token,s.responder_id,'voice:'+body.conversation_id))
    @app.post('/webhooks/telegram',dependencies=[Depends(telegram_auth)])
    async def telegram(r:Request):
        body=await r.json();callback=body.get('callback_query') or {}
        actor=str(callback.get('from',{}).get('id',''));chat=str(callback.get('message',{}).get('chat',{}).get('id',''))
        if chat!=s.telegram_chat_id or actor not in s.telegram_user_ids.split(','):raise HTTPException(403,'Responder or chat is not allowlisted')
        data=callback.get('data',''); parts=data.split(':')
        if len(parts)==3 and parts[0]=='p':
            i=db.incident(parts[1])
            if not i:raise HTTPException(404,'Unknown incident')
            if parts[2]=='rollback':await p.rollback_guard(i)
            proposal=db.propose(i['id'],parts[2],actor,'telegram')
            db.enqueue(i['id'],'telegram','proposal:'+str(body['update_id']),{'text':proposal['readback']+' Approval expires in five minutes.','buttons':[[{'text':'Approve '+parts[2],'callback_data':'a:'+proposal['token']}]]})
            return {'status':'approval_requested'}
        if len(parts)==2 and parts[0]=='a':return public_action(db.approve(parts[1],actor,'telegram'))
        raise HTTPException(400,'Unknown Telegram action')
    @app.post('/webhooks/elevenlabs')
    async def elevenlabs(r:Request):
        raw=await r.body();header=r.headers.get('elevenlabs-signature','')
        try:
            fields=dict(item.split('=',1) for item in header.split(','));stamp=int(fields['t']);signature=fields['v0']
        except (ValueError,KeyError):raise HTTPException(401,'Invalid signature')
        if not s.elevenlabs_webhook_secret or abs(time.time()-stamp)>300:raise HTTPException(401,'Expired signature')
        expected=hmac.new(s.elevenlabs_webhook_secret.encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        secret(signature,expected)
        data=json.loads(raw);conversation=data.get('data',{}).get('conversation_id')
        if not conversation:raise HTTPException(400,'Missing conversation identifier')
        status='failed' if data.get('type')=='call_initiation_failure' else data.get('data',{}).get('status','done')
        db.call_status(conversation,status,hashlib.sha256(raw).hexdigest())
        return {'status':'recorded'}
    @app.get('/operator/incidents',dependencies=[Depends(operator_auth)])
    async def incidents():return db.list_incidents()
    @app.get('/operator/incidents/{id}',dependencies=[Depends(operator_auth)])
    async def incident(id:str):
        row=db.incident(id)
        if not row:raise HTTPException(404,'Unknown incident')
        return row|{'actions':db.actions(id),'timeline':db.timeline(id)}
    @app.post('/operator/reset',dependencies=[Depends(operator_auth)])
    async def reset(body:Reset):return db.reset(body.run_id,'operator')
    @app.post('/operator/incidents/{id}/resume',dependencies=[Depends(operator_auth)])
    async def resume(id:str):return db.resume(id,'operator')
    @app.post('/operator/incidents/{id}/retry-call',dependencies=[Depends(operator_auth)])
    async def retry(id:str,body:Retry):return public_action(db.retry_call(id,'operator',body.purpose))
    @app.post('/operator/actions/{id}/reconcile',dependencies=[Depends(operator_auth)])
    async def reconcile(id:str,body:Reconcile):
        a=db.action(id)
        if not a or a['status']!='unknown':raise Conflict('Action is not unknown')
        i=db.incident(a['incident_id'])
        if a['kind'] in ('dispatch_fix','rollback'):
            session=await p.session(body.provider_id)
            if i['id'] not in session.get('title','') and 'incident:'+i['id'] not in session.get('tags',[]):raise Conflict('Session does not match incident metadata')
            result={'session_id':body.provider_id,'session_url':session.get('url',''),'operator_evidence':body.evidence}
            db.reconcile(id,result,'operator')
            db.update_incident(i['id'],session_id=body.provider_id,session_url=result['session_url'],state='investigating',deadline=time.time()+600)
        elif a['kind']=='call':
            p.require('elevenlabs_api_key')
            detail=await p.request('GET','https://api.elevenlabs.io/v1/convai/conversations/'+body.provider_id,{'xi-api-key':s.elevenlabs_api_key})
            variables=(detail.get('conversation_initiation_client_data') or {}).get('dynamic_variables',{})
            if variables.get('incident_id')!=i['id'] or variables.get('run_id')!=i['run_id']:raise Conflict('Conversation metadata does not match incident and run')
            db.bind_call(i['id'],body.provider_id,None,json.loads(a['payload'])['purpose'])
            db.reconcile(id,{'conversation_id':body.provider_id,'operator_evidence':body.evidence},'operator')
        else:raise Conflict('Telegram has no history reconciliation API; inspect channel and leave unknown, or explicitly record manual outcome using offline operator procedure')
        return public_action(db.action(id))
    return app

def public_action(a):return {k:a[k] for k in ('id','incident_id','kind','status','result')}
