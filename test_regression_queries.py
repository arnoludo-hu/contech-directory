from app.interpreter import fallback
from app.excel_api import store,render,Session

def test_singapore_not_all():
    p=fallback('Which AI startups are based in Singapore?')
    yes,unknown,_=store.filter(p.hard)
    assert 0<len(yes)<len(store.all())
    assert all(r['origin_country']=='SG' for r in yes)

def test_overseas_never_includes_singapore():
    p=fallback('Show overseas solutions')
    yes,_,_=store.filter(p.hard)
    assert yes and all(r['origin_country'] and r['origin_country']!='SG' for r in yes)

def test_verified_psg_fail_closed():
    p=fallback('Which vendors have verified PSG-approved solutions?')
    yes,unknown,_=store.filter(p.hard)
    assert len(yes)==0 and len(unknown)==len(store.all())

def test_generative_design_restricted():
    p=fallback('AI generative design')
    yes,_,_=store.filter(p.hard)
    assert 0<len(yes)<len(store.all())

def test_progress_monitoring_restricted():
    p=fallback('Find computer vision solutions for construction progress monitoring')
    yes,_,_=store.filter(p.hard)
    assert 0<len(yes)<len(store.all())

def test_list_all_still_returns_all():
    p=fallback('List all matching vendors')
    response=render(Session(),p,1,10)
    assert response.total_solutions==len(store.all())
    assert len(response.matches)==10
