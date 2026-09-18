import asyncio
import pytest
from anton.providers import Providers, NotReady
from anton.config import Settings

class GitHub(Providers):
    def __init__(self):
        super().__init__(Settings(deployed_sha='a'*40))
        self.pr={'number':1,'state':'open','draft':False,'html_url':'https://github.com/padmanabh-g/anton-demo-product/pull/1','base':{'ref':'demo/buggy','sha':'a'*40,'repo':{'full_name':self.s.repository}},'head':{'ref':'anton/run/id','sha':'c'*40,'repo':{'full_name':self.s.repository}}}
        self.check={'name':'checkout-regression','head_sha':'c'*40,'status':'completed','conclusion':'success','app':{'id':15368},'html_url':'https://github.com/check/1'}
    async def gh(self,path):
        if '/check-runs' in path:return {'check_runs':[self.check]}
        if '/files' in path:return [{'filename':self.s.regression_path,'status':'modified','changes':2,'patch':'@@ -1 +1 @@\n-return total > MINIMUM;\n+return total >= MINIMUM;'}]
        if '/branches/' in path:return {'commit':{'sha':'a'*40}}
        return self.pr

@pytest.mark.parametrize('mutation',[lambda p:p.pr.update(draft=True),lambda p:p.pr['base'].update(ref='main'),lambda p:p.pr['head'].update(ref='wrong'),lambda p:p.check.update(head_sha='d'*40),lambda p:p.check.update(conclusion='failure'),lambda p:p.check['app'].update(id=1)])
def test_gate_rejects_untrusted_or_wrong_head(mutation):
    p=GitHub();mutation(p)
    with pytest.raises(NotReady):asyncio.run(p.verify_pr({'branch':'anton/run/id','deployed_sha':'a'*40,'strategy':'dispatch_fix'},1))

def test_gate_records_exact_sha_and_checks():
    evidence=asyncio.run(GitHub().verify_pr({'branch':'anton/run/id','deployed_sha':'a'*40,'strategy':'dispatch_fix'},1))
    assert evidence['head']=='c'*40
    assert evidence['checks'][0]['name']=='checkout-regression'
