from fastapi.testclient import TestClient
from app.excel_api import app
from app.explanations import explain
from app.models import QueryPlan, FilterGroup, Predicate
from app.excel_store import ExcelStore

client=TestClient(app)

def test_card_explanations_are_not_generic():
    response=client.post('/api/v1/search',json={'message':'List all matching vendors','page_size':5})
    assert response.status_code==200,response.text
    for item in response.json()['matches']:
        assert 'Candidate found in imported ConTech workbook' not in ' '.join(item['reasons'])
        assert item['verification_status']=='imported_unverified'
        assert isinstance(item['evidence'],list)
        assert item['psg_status']=='unknown'

def test_origin_filter_has_explicit_reason():
    response=client.post('/api/v1/search/filters',json={'filters':{'origin_country':'SG'}})
    assert response.status_code==200
    assert response.json()['matches']
    assert all('Country-of-origin filter matched:' in ' '.join(x['reasons']) for x in response.json()['matches'])

def test_source_terms_not_invented():
    row={'summary':'Uses 360 imagery for site progress tracking','source_use_cases':'','source_category':'','use_cases':[],'technologies':[],'origin_label':'Japan','origin_country':'JP','source_references':None,'local_presence_claim':None,'historical_psg_claim':None,'psg_status':'unknown'}
    plan=QueryPlan(problem='progress monitoring for hospitals')
    explanation=explain(row,plan,42)
    assert 'progress' in ' '.join(explanation['reasons'])
    assert 'hospitals' not in ' '.join(explanation['reasons'])
    assert explanation['verification_status']=='imported_unverified'

def test_historical_psg_not_claimed_current():
    row=next((r for r in ExcelStore().all() if (r.get('historical_psg_claim') or '').lower()=='yes'),None)
    assert row is not None
    explanation=explain(row,QueryPlan(problem='PSG'),0)
    assert any('Historical PSG Yes' in x for x in explanation['limitations'])
    assert explanation['psg_status']=='unknown'

def test_unknown_origin_not_asserted():
    row={'summary':'','source_use_cases':'','source_category':'','use_cases':[],'technologies':[],'origin_label':None,'origin_country':None,'source_references':None,'local_presence_claim':None,'historical_psg_claim':None,'psg_status':'unknown'}
    e=explain(row,QueryPlan(problem='design'),5)
    assert not any('Country-of-origin' in x for x in e['reasons'])
