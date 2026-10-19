"""Read-only directory endpoints and narrowly scoped administrative editing."""
from fastapi import APIRouter,HTTPException,Header
from pydantic import BaseModel,Field
from sqlalchemy import text
from .repository import Repository
import os
router=APIRouter(prefix='/api/v1')

@router.get('/taxonomy')
def taxonomy():
    try:
        with Repository().engine.connect() as db:
            def rows(table,key='code',label='label'):
                return [dict(r) for r in db.execute(text(f'SELECT {key} AS code,{label} AS label FROM contech.{table} ORDER BY {label}')).mappings()]
            return {'technologies':rows('technology_categories'),'use_cases':rows('use_cases'),'customer_segments':rows('customer_segments'),'countries':rows('countries','country_code','country_name')}
    except Exception:raise HTTPException(503,'Directory taxonomy unavailable')

@router.get('/solutions/{solution_id}')
def solution_detail(solution_id:str):
    from uuid import UUID
    try:UUID(solution_id)
    except ValueError:raise HTTPException(422,'Invalid solution ID')
    sql='''SELECT s.solution_id::text,c.company_id::text,c.legal_name company,s.solution_name solution,
    coalesce(s.summary,'') summary,s.material_ai_description,c.origin_country_code origin_country,
    c.headquarters_country_code headquarters_country,s.product_url,c.website_url company_website,s.maturity::text maturity
    FROM contech.solutions s JOIN contech.companies c ON c.company_id=s.company_id
    WHERE s.solution_id=:id AND s.status='published' AND c.status='published' AND s.ai_eligibility='verified' '''
    try:
        with Repository().engine.connect() as db:
            r=db.execute(text(sql),{'id':solution_id}).mappings().first()
            if not r:raise HTTPException(404,'Published solution not found')
            out=dict(r)
            def labels(sql):return [x[0] for x in db.execute(text(sql),{'id':solution_id})]
            out['technologies']=labels("SELECT t.label FROM contech.solution_technologies st JOIN contech.technology_categories t ON t.technology_id=st.technology_id WHERE st.solution_id=:id AND st.confidence='verified'")
            out['use_cases']=labels("SELECT u.label FROM contech.solution_use_cases su JOIN contech.use_cases u ON u.use_case_id=su.use_case_id WHERE su.solution_id=:id AND su.support_status='yes'")
            out['customer_segments']=labels("SELECT c.label FROM contech.solution_segments ss JOIN contech.customer_segments c ON c.segment_id=ss.segment_id WHERE ss.solution_id=:id AND ss.fit_status='yes'")
            flags=db.execute(text('''SELECT
            EXISTS(SELECT 1 FROM contech.singapore_legal_entities e WHERE e.company_id=:cid AND e.incorporation_status='yes' AND e.verification='verified') singapore_entity,
            EXISTS(SELECT 1 FROM contech.partner_relationships p WHERE p.company_id=:cid AND (p.solution_id IS NULL OR p.solution_id=:id) AND p.territory_country_code='SG' AND p.role IN ('reseller','distributor') AND p.verification='verified' AND (p.valid_from IS NULL OR p.valid_from<=CURRENT_DATE) AND (p.valid_to IS NULL OR p.valid_to>=CURRENT_DATE)) singapore_reseller,
            EXISTS(SELECT 1 FROM contech.support_arrangements a WHERE a.company_id=:cid AND (a.solution_id IS NULL OR a.solution_id=:id) AND a.country_code='SG' AND a.verification='verified' AND a.support_mode IN ('direct_local','partner_local')) singapore_support,
            EXISTS(SELECT 1 FROM contech.currently_verified_psg p WHERE p.solution_id=:id) psg_verified'''),{'cid':out['company_id'],'id':solution_id}).mappings().one()
            out.update({k:flags[k] for k in ('singapore_entity','singapore_reseller','singapore_support')})
            out['psg_status']='verified_current' if flags['psg_verified'] else 'unknown_or_not_current'
            out['psg_verified_at']=None
            out['source_urls']=Repository().sources([solution_id]).get(solution_id,[])
            return out
    except HTTPException:raise
    except Exception:raise HTTPException(503,'Solution profile unavailable')

class AdminSolutionPatch(BaseModel):
    summary:str|None=Field(default=None,max_length=5000)
    material_ai_description:str|None=Field(default=None,max_length=5000)
    product_url:str|None=None

def check_admin(key:str|None):
    import hmac
    expected=os.getenv('ADMIN_API_KEY')
    if not expected or not key or not hmac.compare_digest(key,expected):raise HTTPException(401,'Administrator authentication required')

@router.get('/admin/solutions')
def admin_solutions(x_admin_key:str|None=Header(default=None)):
    check_admin(x_admin_key)
    with Repository().engine.connect() as db:
        return {'items':[dict(r) for r in db.execute(text('''SELECT s.solution_id::text,s.solution_name,c.legal_name company,s.status::text status,s.ai_eligibility::text ai_eligibility,s.summary FROM contech.solutions s JOIN contech.companies c ON c.company_id=s.company_id ORDER BY s.updated_at DESC LIMIT 200''')).mappings()]}

@router.patch('/admin/solutions/{solution_id}')
def admin_update(solution_id:str,patch:AdminSolutionPatch,x_admin_key:str|None=Header(default=None)):
    check_admin(x_admin_key)
    from uuid import UUID
    try:UUID(solution_id)
    except ValueError:raise HTTPException(422,'Invalid solution ID')
    updates=patch.model_dump(exclude_unset=True)
    if not updates:raise HTTPException(422,'No changes submitted')
    # Do not publish records or alter verification status through this endpoint.
    clauses=','.join(f'{k}=:{k}' for k in updates)
    with Repository().engine.begin() as db:
        r=db.execute(text(f'UPDATE contech.solutions SET {clauses},updated_at=now() WHERE solution_id=:id RETURNING solution_id::text'),{**updates,'id':solution_id}).first()
    if not r:raise HTTPException(404,'Solution not found')
    return {'solution_id':r[0],'updated':list(updates)}
