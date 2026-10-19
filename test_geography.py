from app.interpreter import fallback
from app.excel_api import store

def test_australia_or_us_excludes_singapore():
    p=fallback('Show AI solutions from Australia or the US')
    yes,unknown,excluded=store.filter(p.hard)
    assert yes
    assert {r['origin_country'] for r in yes} <= {'AU','US'}
    assert all(r['company'].casefold()!='esgpedia' for r in yes)

def test_overseas_with_local_reseller_not_mistaken_for_sg_origin():
    p=fallback('Show overseas solutions with a Singapore reseller')
    assert len(p.hard)==2
    assert {g.any_of[0].field for g in p.hard}=={'origin_country','singapore_reseller'}

def test_exclude_us_au():
    p=fallback('Exclude solutions from US and Australia')
    yes,_,_=store.filter(p.hard)
    assert all(r['origin_country'] not in {'AU','US'} for r in yes)

def test_singapore_based():
    p=fallback('Which AI startups are based in Singapore?')
    yes,_,_=store.filter(p.hard)
    assert yes and all(r['origin_country']=='SG' for r in yes)
