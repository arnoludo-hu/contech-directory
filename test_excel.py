from fastapi.testclient import TestClient
from app.main import app
from app.excel_store import ExcelStore
from app.models import FilterGroup,Predicate

client=TestClient(app)
def test_health():
    r=client.get('/health');assert r.status_code==200;assert r.json()['records']>0

def test_real_excel_records():
    r=client.post('/api/v1/search',json={'message':'List all matching vendors','page_size':10})
    assert r.status_code==200,r.text
    j=r.json();assert j['total_solutions']>0;assert len(j['matches'])==10
    assert all('not independently verified' in ' '.join(x['limitations']) for x in j['matches'])

def test_count_from_excel():
    r=client.post('/api/v1/search',json={'message':'How many vendors meet these criteria?'})
    j=r.json();assert j['total_companies']==len({r['company_id'] for r in ExcelStore().all()})

def test_psg_unknown_excluded():
    r=client.post('/api/v1/search/filters',json={'filters':{'psg_current':'true'}})
    assert r.status_code==200;assert r.json()['total_solutions']==0
    assert r.json()['unverified_count']>0

def test_singapore_entity_unknown_excluded():
    r=client.post('/api/v1/search/filters',json={'filters':{'singapore_entity':'true'}})
    assert r.json()['total_solutions']==0

def test_origin_filter_and_pagination():
    r=client.post('/api/v1/search/filters',json={'filters':{'origin_country':'SG'},'page_size':2})
    j=r.json();assert all(ExcelStore().get(x['solution_id'])['origin_country']=='SG' for x in j['matches'])
    if j['total_solutions']>2:
        p=client.get(f"/api/v1/sessions/{j['session_id']}/results?page=2&page_size=2")
        assert p.status_code==200
        assert {x['solution_id'] for x in j['matches']}.isdisjoint({x['solution_id'] for x in p.json()['matches']})

def test_profile_is_staging():
    sid=ExcelStore().all()[0]['solution_id'];r=client.get('/api/v1/solutions/'+sid)
    assert r.status_code==200;assert r.json()['publication_status']=='staging'
    assert r.json()['singapore_entity'] is None

def test_admin_disabled():assert client.get('/api/v1/admin/solutions').status_code==501

def test_unknown_not_false():
    store=ExcelStore();p=Predicate(field='psg_current',op='eq',values=['false'])
    assert store.matches(store.all()[0],p) is None

def test_invalid_filter_rejected():
    assert client.post('/api/v1/search/filters',json={'filters':{'something':'yes'}}).status_code==422
