from __future__ import annotations
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from .models import Predicate,FilterGroup
import os

BASE='''SELECT s.solution_id::text AS solution_id,c.company_id::text AS company_id,c.legal_name AS company,s.solution_name AS solution,
 COALESCE(s.summary,'') AS summary,COALESCE(d.search_text,'') AS search_text,
 c.origin_country_code AS origin_country,c.headquarters_country_code AS headquarters_country,
 s.maturity::text AS maturity
 FROM contech.solutions s JOIN contech.companies c ON c.company_id=s.company_id
 LEFT JOIN contech.solution_search_documents d ON d.solution_id=s.solution_id
 WHERE s.status='published' AND c.status='published' AND s.ai_eligibility='verified' '''

# Whitelisted SQL expressions only. No user-controlled SQL identifiers.
EXP={
 'origin_country':'c.origin_country_code',
 'headquarters_country':'c.headquarters_country_code',
 'maturity':'s.maturity::text',
 'company_name':'lower(c.legal_name)',
 'solution_name':'lower(s.solution_name)',
 'singapore_entity':"EXISTS (SELECT 1 FROM contech.singapore_legal_entities e WHERE e.company_id=c.company_id AND e.incorporation_status='yes' AND e.verification='verified')",
 'singapore_reseller':"EXISTS (SELECT 1 FROM contech.partner_relationships r WHERE r.company_id=c.company_id AND (r.solution_id IS NULL OR r.solution_id=s.solution_id) AND r.territory_country_code='SG' AND r.role IN ('reseller','distributor') AND r.verification='verified' AND (r.valid_from IS NULL OR r.valid_from<=CURRENT_DATE) AND (r.valid_to IS NULL OR r.valid_to>=CURRENT_DATE))",
 'singapore_support':"EXISTS (SELECT 1 FROM contech.support_arrangements a WHERE a.company_id=c.company_id AND (a.solution_id IS NULL OR a.solution_id=s.solution_id) AND a.country_code='SG' AND a.support_mode IN ('direct_local','partner_local') AND a.verification='verified')",
 'psg_current':"EXISTS (SELECT 1 FROM contech.currently_verified_psg p WHERE p.solution_id=s.solution_id)",
 'technology':"EXISTS (SELECT 1 FROM contech.solution_technologies st JOIN contech.technology_categories t ON t.technology_id=st.technology_id WHERE st.solution_id=s.solution_id AND st.confidence='verified' AND t.code = :VALUE)",
 'use_case':"EXISTS (SELECT 1 FROM contech.solution_use_cases su JOIN contech.use_cases u ON u.use_case_id=su.use_case_id WHERE su.solution_id=s.solution_id AND su.support_status='yes' AND u.code = :VALUE)",
 'customer_segment':"EXISTS (SELECT 1 FROM contech.solution_segments ss JOIN contech.customer_segments cs ON cs.segment_id=ss.segment_id WHERE ss.solution_id=s.solution_id AND ss.fit_status='yes' AND cs.code = :VALUE)",
}
# Pricing not yet represented by v2 schema: preference never creates unsupported hard filter.

def predicate_sql(p:Predicate,params:dict,idx:int)->str:
    if p.field=='price_tier':
        raise ValueError('Price tier is not yet in the database; cannot enforce as a hard filter')
    if p.field=='singapore_presence':
        return '('+' OR '.join(predicate_sql(Predicate(field=k,op=p.op,values=p.values),params,idx*10+i) for i,k in enumerate(('singapore_entity','singapore_reseller','singapore_support')))+')' if p.values==['true'] else 'NOT ('+' OR '.join(predicate_sql(Predicate(field=k,op='eq',values=['true']),params,idx*10+i) for i,k in enumerate(('singapore_entity','singapore_reseller','singapore_support')))+')'
    expr=EXP[p.field]
    if p.field in ('singapore_entity','singapore_reseller','singapore_support','psg_current'):
        truth=p.values[0]=='true'; neg=p.op=='not_in';return ('NOT ' if truth==neg else '')+'('+expr+')'
    if p.field in ('technology','use_case','customer_segment'):
        clauses=[]
        for j,v in enumerate(p.values):
            key=f'f_{idx}_{j}';params[key]=v.lower();clauses.append(expr.replace(':VALUE',':'+key))
        joined='('+' OR '.join(clauses)+')'
        return 'NOT '+joined if p.op in ('not_in','not_contains') else joined
    vals=[]
    for j,v in enumerate(p.values):
        key=f'f_{idx}_{j}';params[key]=v.lower() if p.field in ('company_name','solution_name') else v.upper() if p.field.endswith('country') else v
        vals.append(':'+key)
    if p.op in ('contains','not_contains'):
        key=f'f_{idx}_like';params[key]='%'+p.values[0].lower()+'%';condition=f'{expr} ILIKE :{key}'
    else:condition=f'{expr} IN ('+','.join(vals)+')'
    if p.op in ('not_in','not_contains'):
        # Unknown must not be treated as a verified negative.
        return f'({expr} IS NOT NULL AND NOT ({condition}))'
    return '('+condition+')'

def build_where(groups:list[FilterGroup]):
    params={};parts=[]
    for i,g in enumerate(groups):
        pieces=[predicate_sql(p,params,i*100+j) for j,p in enumerate(g.any_of)]
        parts.append('('+' OR '.join(pieces)+')')
    return ' AND '.join(parts),params

class Repository:
    def __init__(self,url=None):self.engine=create_engine(url or os.environ['DATABASE_URL'],pool_pre_ping=True)
    def search(self,groups,problem='',page=1,page_size=10,all_rows=False):
        where,params=build_where(groups)
        base=BASE+(' AND '+where if where else '')
        with self.engine.connect() as db:
            total=db.execute(text('SELECT count(*) AS n,count(DISTINCT company_id) AS companies FROM ('+base+') q'),params).mappings().one()
            # Candidate pool: all eligible rows; semantic ranking happens after exact filtering.
            rows=[dict(r) for r in db.execute(text(base+' ORDER BY c.legal_name,s.solution_name'),params).mappings()]
        return rows,int(total['n']),int(total['companies'])
    def sources(self,ids):
        if not ids:return {}
        sql='''SELECT s.solution_id::text sid,e.source_url url FROM contech.solutions s
          JOIN contech.claims c ON c.subject_type='solution' AND c.subject_id=s.solution_id AND c.verification='verified'
          JOIN contech.claim_evidence ce ON ce.claim_id=c.claim_id JOIN contech.source_evidence e ON e.evidence_id=ce.evidence_id
          WHERE s.solution_id = ANY(CAST(:ids AS uuid[])) AND e.source_url IS NOT NULL AND e.internal_only=false'''
        from collections import defaultdict
        out=defaultdict(list)
        with self.engine.connect() as db:
            for r in db.execute(text(sql),{'ids':ids}):out[r.sid].append(r.url)
        return dict(out)
