"""Evidence-grounded, deterministic result-card explanations for Excel staging data.

No LLM-generated factual assertions: each statement is derived from stored fields.
"""
from __future__ import annotations
import re
from .excel_store import code

STOP = {'ai','the','and','for','with','show','find','solutions','solution','vendors','vendor','which','from','that','tools','tool','need','please','are','in','of','to','a','an','based','on','me','some'}

def words(value):
    return {x for x in re.findall(r'[a-z0-9]+',str(value or '').lower()) if x not in STOP and len(x)>2}

def labels(value):
    return ', '.join(str(x).replace('_',' ') for x in value if x)

def explain(row,plan,score):
    """Return reason statements and structured transparency fields.

    Source taxonomy is explicitly labelled suggested, never independently verified.
    """
    reasons=[]; evidence=[]; matched=[]; limitations=[]
    for group in plan.hard:
        for pred in group.any_of:
            f=pred.field
            if f=='origin_country' and row.get('origin_country'):
                country=row.get('origin_label') or row['origin_country']
                if pred.op in ('eq','in'):
                    reason=f"Country-of-origin filter matched: {country} (as recorded in the imported workbook)."
                else:
                    reason=f"Country-of-origin exclusion passed: {country} (as recorded in the imported workbook)."
                if reason not in reasons:reasons.append(reason)
                matched.append('origin_country')
            elif f in ('technology','use_case','customer_segment'):
                value={'technology':row.get('technologies',[]),'use_case':row.get('use_cases',[]),'customer_segment':row.get('customer_segments',[])}[f]
                source={'technology':row.get('source_category'),'use_case':row.get('source_use_cases'),'customer_segment':None}[f]
                text=labels(value) or source
                if text:
                    reason=f"Imported {f.replace('_',' ')} classification matches this filter: {text} (provisional)."
                    if reason not in reasons:reasons.append(reason)
                    matched.append(f)
            elif f in ('singapore_presence','singapore_entity','singapore_reseller','singapore_support','psg_current'):
                # These fields are only emitted as matches when explicitly verified in structured data.
                if row.get(f) is True:
                    reasons.append(f"Verified structured attribute matches: {f.replace('_',' ')}.")
                    matched.append(f)
    query=words(plan.problem)
    # Include only terms actually found in source text, not LLM-imagined capabilities.
    source_text=' '.join(str(row.get(k) or '') for k in ('summary','source_use_cases','source_category'))
    hits=sorted(query & words(source_text))
    if hits:
        reasons.append('The imported description shares these query terms: '+', '.join(hits[:6])+'.')
        matched.append('description_terms')
        evidence.append({'field':'source_description','excerpt':source_text[:240], 'status':'imported_unverified'})
    elif not reasons and plan.problem.strip():
        reasons.append('Retrieved as a provisional candidate by search ranking; no specific capability match has been established.')
    elif not reasons:
        reasons.append('Included in the requested directory listing; no capability-based match was assessed.')
    if row.get('use_cases'):
        evidence.append({'field':'suggested_use_cases','excerpt':labels(row['use_cases']), 'status':'provisional_classification'})
    if row.get('technologies'):
        evidence.append({'field':'suggested_technologies','excerpt':labels(row['technologies']), 'status':'provisional_classification'})
    if row.get('origin_label'):
        evidence.append({'field':'origin_country','excerpt':row['origin_label'], 'status':'imported_unverified'})
    if row.get('source_references'):
        evidence.append({'field':'source_workbook_references','excerpt':str(row['source_references'])[:240], 'status':'imported_unverified'})
    if row.get('local_presence_claim'):
        limitations.append('Historical Singapore presence claim exists; legal entity, reseller and support arrangements are not independently verified.')
    if row.get('historical_psg_claim') and code(row['historical_psg_claim'])=='yes':
        limitations.append('Historical PSG Yes recorded; current product/package approval has not been verified.')
    else:
        limitations.append('Current PSG package approval is unknown, not a negative approval finding.')
    limitations.append('AI capabilities and imported classifications have not been independently verified.')
    limitations.append('Relevance score is a provisional retrieval score, not a vendor quality rating.')
    return {
        'reasons':reasons,
        'limitations':limitations,
        'matched_fields':list(dict.fromkeys(matched)),
        'evidence':evidence,
        'verification_status':'imported_unverified',
        'origin_country':row.get('origin_country'),
        'origin_label':row.get('origin_label'),
        'use_cases':row.get('use_cases') or [],
        'technologies':row.get('technologies') or [],
        'psg_status':row.get('psg_status') or 'unknown',
        'singapore_presence_status':'unverified' if row.get('local_presence_claim') else 'unknown',
    }
