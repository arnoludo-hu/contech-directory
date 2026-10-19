"""Excel-only FastAPI backend. All records are staging/unverified."""
from __future__ import annotations
import os,re,math
from collections import Counter
from threading import RLock
from uuid import uuid4
from difflib import SequenceMatcher
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from .models import QueryPlan,SearchRequest,SearchResponse,Match,FilterGroup,Predicate
from .interpreter import interpret
from .state import merge
from .excel_store import ExcelStore,code
from .explanations import explain
from fastapi.responses import JSONResponse

_semantic_model=None
def semantic_model():
    global _semantic_model
    if os.getenv("ENABLE_LOCAL_EMBEDDINGS","false").lower()!="true":return None
    if _semantic_model is None:
        from sentence_transformers import SentenceTransformer
        _semantic_model=SentenceTransformer(os.getenv("EMBEDDING_MODEL","sentence-transformers/all-MiniLM-L6-v2"))
    return _semantic_model

app=FastAPI(title='ConTech Excel Search API (staging)',version='1.0')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000','http://127.0.0.1:3000'],allow_methods=['GET','POST'],allow_headers=['*'])
store=ExcelStore()
_sessions={};_lock=RLock()
class Session:
    def __init__(self):self.id=str(uuid4());self.plan=QueryPlan();self.last_ids=[];self.last_query='';self.snapshot=[]
class FilterRequest(BaseModel):
    session_id:str|None=None
    filters:dict[str,str]=Field(default_factory=dict)
    page:int=Field(default=1,ge=1)
    page_size:int=Field(default=10,ge=1,le=100)

def session(sid):
    with _lock:
        if sid:
            if sid not in _sessions:raise HTTPException(404,'Conversation expired or server restarted; start a new search')
            return _sessions[sid]
        s=Session();_sessions[s.id]=s;return s

def tokenize(s):return set(re.findall(r'[a-z0-9]+',str(s or '').lower()))-{'the','for','and','with','show','find','solutions','vendors','ai','which','are','there','some','me','tools','need','want'}
def relevance(row,problem):
    if not problem:return 0.0
    q=tokenize(problem)
    if not q:return 0.0
    content=' '.join(str(x or '') for x in [row['company'],row['solution'],row['summary'],row['source_category'],row['source_use_cases'],*row['technologies'],*row['use_cases']])
    tokens=tokenize(content)
    overlap=len(q&tokens)/max(1,len(q))
    fuzzy=max(SequenceMatcher(None,code(problem),code(row['company'])).ratio(),SequenceMatcher(None,code(problem),code(row['solution'])).ratio())
    return min(100,round(100*(0.85*overlap+0.15*fuzzy),1))

def score_rows(rows,plan):
    # Stable deterministic fallback, no external embedding download required.
    scored=[]
    model=semantic_model() if plan.problem else None
    vector_scores={}
    if model and rows:
        texts=[' '.join(str(v or '') for v in [r['solution'],r['summary'],r['source_category'],r['source_use_cases'],*r['use_cases'],*r['technologies']]) for r in rows]
        embeddings=model.encode([plan.problem,*texts],normalize_embeddings=True)
        for r,vec in zip(rows,embeddings[1:]):
            vector_scores[r['solution_id']]=max(0.0,float(embeddings[0] @ vec))*100
    for r in rows:
        lexical=relevance(r,plan.problem)
        s=round(0.65*vector_scores[r['solution_id']]+0.35*lexical,1) if model else lexical
        scored.append((s,r))
    return sorted(scored,key=lambda x:(-x[0],x[1]['company'].casefold(),x[1]['solution_id']))

def render(s,plan,page,page_size,from_snapshot=False):
    confirmed,unknown,excluded=store.filter(plan.hard)
    if from_snapshot and s.snapshot:
        byid={r['solution_id']:r for r in confirmed}
        scored=[(relevance(byid[i],plan.problem),byid[i]) for i in s.snapshot if i in byid]
    else:
        scored=score_rows(confirmed,plan)
        s.snapshot=[r['solution_id'] for _,r in scored]
    # Search discovery is not the same as browse-all. Suppress irrelevant candidates.
    if plan.intent not in ('list','count','compare') and plan.problem.strip():
        if not plan.hard:
            scored=[(score,r) for score,r in scored if score >= float(os.getenv('MIN_RELEVANCE_SCORE','25'))]
        else:
            # Structured filters are authoritative; only rank within eligible set.
            pass
    if plan.intent=='compare' and plan.compare_positions:
        if not s.last_ids:raise HTTPException(409,'No previous results to compare')
        wanted=[s.last_ids[i-1] for i in plan.compare_positions if 0<i<=len(s.last_ids)]
        if len(wanted)!=len(plan.compare_positions):raise HTTPException(422,'Invalid result position')
        lookup={r['solution_id']:(score,r) for score,r in scored}
        scored=[lookup[i] for i in wanted if i in lookup]
    else:s.last_ids=[r['solution_id'] for _,r in scored]
    s.snapshot=[r['solution_id'] for _,r in scored]
    total=len(scored);companies=len({r['company_id'] for _,r in scored})
    start=(page-1)*page_size
    matches=[]
    for score,r in scored[start:start+page_size]:
        explanation=explain(r,plan,score)
        matches.append(Match(solution_id=r['solution_id'],company_id=r['company_id'],company=r['company'],solution=r['solution'],score=score,source_urls=r['source_urls'],**explanation))
    message=(f'{total} provisional matching solution records from {companies} company labels. All records are staging and unverified.' if total else 'No matches meet all specified filters. Unknown values are excluded from mandatory filters; try removing a constraint.')
    if plan.intent=='count':message=f'{total} provisional solution records from {companies} company labels satisfy the current database filters. This is not a verified market count.'
    if plan.intent=='compare':message='Comparison of previously selected result positions. All claims remain unverified.'
    if plan.hard and not total and unknown:
        message+=f' {len(unknown)} records have unknown required attributes; they are not verified matches.'
    if plan.preferences:message+=' Preferences requiring unverified pricing or capabilities are not used to assert affordability.'
    return SearchResponse(session_id=s.id,intent=plan.intent,applied_filters=plan.hard,preferences=plan.preferences,total_solutions=total,total_companies=companies,page=page,page_size=page_size,matches=matches,unverified_count=len(unknown),clarification=plan.clarification,message=message)

@app.get('/health')
def health():return {'status':'ok','mode':'excel_staging','records':len(store.all()),'database':str(store.path)}

@app.post('/api/v1/search',response_model=SearchResponse)
def search(req:SearchRequest):
    s=session(req.session_id)
    has_state=bool(s.last_ids or s.plan.hard or s.plan.problem)
    p=interpret(req.message,has_state=has_state)
    if p.intent=='compare' and p.compare_positions and has_state:p.operation='add'
    if re.search(r'\b(list all|how many)\b',req.message.lower()) and has_state and not re.search(r'\b(reset|start again)\b',req.message.lower()):p.operation='add'
    if p.operation=='add' and has_state and p.problem==req.message:p.problem=''
    s.plan=merge(s.plan,p);s.last_query=req.message
    return render(s,s.plan,req.page,req.page_size)

@app.post('/api/v1/search/filters',response_model=SearchResponse)
def filter_search(req:FilterRequest):
    s=session(req.session_id)
    allowed={'technology','use_case','origin_country','singapore_entity','singapore_reseller','singapore_support','singapore_presence','psg_current','customer_segment'}
    groups=[]
    for k,v in req.filters.items():
        if k not in allowed:raise HTTPException(422,f'Unsupported filter: {k}')
        if not v:continue
        groups.append(FilterGroup(any_of=[Predicate(field=k,op='eq',values=[v])]))
    # Replace filters, preserve operational problem for current conversation.
    s.plan.hard=groups;s.plan.intent='refine'
    return render(s,s.plan,req.page,req.page_size)

@app.get('/api/v1/sessions/{session_id}/results',response_model=SearchResponse)
def paginate(session_id:str,page:int=1,page_size:int=10):
    if page<1 or page_size<1 or page_size>100:raise HTTPException(422,'Invalid pagination')
    s=session(session_id)
    return render(s,s.plan,page,page_size,from_snapshot=True)

@app.get('/api/v1/taxonomy')
def taxonomy():return store.taxonomy()

@app.get('/api/v1/solutions/{solution_id}')
def detail(solution_id:str):
    r=store.get(solution_id)
    if not r:raise HTTPException(404,'Solution not found')
    return {k:r[k] for k in ('solution_id','company_id','company','solution','summary','material_ai_description','origin_country','headquarters_country','product_url','company_website','maturity','technologies','use_cases','customer_segments','singapore_entity','singapore_reseller','singapore_support','psg_status','psg_verified_at','source_urls','publication_status','ai_eligibility')}

@app.get('/api/v1/admin/solutions')
def admin_list():
    raise HTTPException(501,'Excel mode is read-only. Edit the workbook offline; admin editing is disabled.')
@app.patch('/api/v1/admin/solutions/{solution_id}')
def admin_edit(solution_id:str):
    raise HTTPException(501,'Excel mode is read-only. Admin editing is disabled.')

@app.post('/api/v1/search/debug')
def debug_search(req:SearchRequest):
    # Development-only endpoint; disable for public deployment.
    if os.getenv('ENABLE_SEARCH_DEBUG','false').lower()!='true':
        raise HTTPException(404,'Not found')
    s=session(req.session_id)
    p=interpret(req.message,has_state=bool(s.last_ids or s.plan.hard or s.plan.problem))
    merged=merge(s.plan,p)
    yes,unknown,no=store.filter(merged.hard)
    return {'parsed_plan':merged.model_dump(),'eligible_before_relevance':len(yes),
            'unknown_required_attributes':len(unknown),'excluded_by_filters':len(no),
            'example_eligible_ids':[r['solution_id'] for r in yes[:10]],
            'sample_unknown_fields':unknown[0][1] if unknown else []}
