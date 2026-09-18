from fastapi.testclient import TestClient
from anton.api import create_app
from anton.config import Settings

def client(tmp_path):
    return TestClient(create_app(Settings(db_path=str(tmp_path/'api.db'),run_id='r',deployed_sha='a'*40,datadog_secret='dd',voice_secret='voice',telegram_secret='tg',telegram_chat_id='1',telegram_user_ids='2',operator_secret='op',worker_enabled='false')))

def test_unauthorized_creates_nothing(tmp_path):
    with client(tmp_path) as c:
        assert c.post('/webhooks/datadog',json={}).status_code==401
        assert c.post('/webhooks/telegram',json={},headers={'X-Telegram-Bot-Api-Secret-Token':'bad'}).status_code==401
        assert c.get('/operator/incidents',headers={'Authorization':'Bearer op'}).json()==[]

def test_voice_spoofing_rejected(tmp_path):
    with client(tmp_path) as c:
        r=c.post('/voice/propose',headers={'X-Anton-Secret':'voice'},json={'conversation_id':'made-up','run_id':'r','action':'dispatch_fix'})
        assert r.status_code==409

def test_telegram_actor_chat_allowlist(tmp_path):
    with client(tmp_path) as c:
        body={'update_id':1,'callback_query':{'id':'x','from':{'id':9},'message':{'chat':{'id':1}},'data':'p:x:dispatch_fix'}}
        assert c.post('/webhooks/telegram',headers={'X-Telegram-Bot-Api-Secret-Token':'tg'},json=body).status_code==403
