"""Read-only, explicitly unverified Excel staging repository."""
from __future__ import annotations
import os,re,threading
from pathlib import Path
from openpyxl import load_workbook
from difflib import SequenceMatcher

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_FILE=ROOT/'ConTech_Master_Database_v1.xlsx'
def clean(value):
    if value is None:return None
    value=str(value).strip()
    return None if not value or value.lower() in ('none','nan','n/a','#n/a','0','unknown','not verified') else value

def code(s):return re.sub(r'[^a-z0-9]+','_',str(s).lower()).strip('_')

COUNTRIES={'singapore':'SG','japan':'JP','australia':'AU','united states':'US','usa':'US','united kingdom':'GB','uk':'GB','china':'CN','hong kong':'HK','south korea':'KR','korea':'KR','germany':'DE','france':'FR','india':'IN','malaysia':'MY','canada':'CA','israel':'IL','netherlands':'NL','spain':'ES','switzerland':'CH','finland':'FI','sweden':'SE','taiwan':'TW','indonesia':'ID','vietnam':'VN','thailand':'TH','new zealand':'NZ','austria':'AT','belgium':'BE','czech republic':'CZ','norway':'NO','spain':'ES','us':'US'}

def read_sheet(wb,name):
    it=iter(wb[name].values);headers=[str(x).strip() for x in next(it)]
    return [dict(zip(headers,row)) for row in it if any(x is not None for x in row)]

class ExcelStore:
    def __init__(self,path=None):
        self.path=Path(path or os.getenv('CONTECH_EXCEL_PATH') or DEFAULT_FILE)
        self.lock=threading.RLock();self.stamp=None;self.rows=[];self.by_id={};self.tax={}
        self.refresh()
    def refresh(self):
        with self.lock:
            if not self.path.exists():raise FileNotFoundError(f'Excel file missing: {self.path}')
            stamp=self.path.stat().st_mtime_ns
            if self.stamp==stamp:return
            wb=load_workbook(self.path,read_only=True,data_only=True)
            try:
                vendors={str(r['Vendor ID']):r for r in read_sheet(wb,'Master Vendors')}
                pres={str(r['Vendor ID']):r for r in read_sheet(wb,'Singapore Presence')}
                psg={str(r['Solution ID']):r for r in read_sheet(wb,'PSG Verification')}
                tax={}
                for sheet,key,label in [('Technology Taxonomy','technologies','AI technology'),('AI Use Cases','use_cases','Use case')]:
                    tax[key]=[{'code':code(r[label]),'label':str(r[label])} for r in read_sheet(wb,sheet) if clean(r.get(label))]
                rows=[]
                for s in read_sheet(wb,'Master Solutions'):
                    sid=str(s['Solution ID']);vid=str(s['Vendor ID']);v=vendors.get(vid)
                    if not v:continue
                    p=pres.get(vid,{}) ; g=psg.get(sid,{})
                    origin=clean(v.get('Country of origin (raw)'))
                    raw_tech=clean(s.get('AI technology (suggested)'))
                    raw_use=clean(s.get('AI use case (suggested)'))
                    uses=[x.strip() for x in (raw_use or '').split(';') if x.strip()]
                    tech=[x.strip() for x in (raw_tech or '').split(';') if x.strip()]
                    website=clean(s.get('Website (raw)')) or clean(v.get('Website (raw)'))
                    if website and not website.startswith(('https://','http://')):website=None
                    row={'solution_id':sid,'company_id':vid,'company':str(v['Canonical label (provisional)']),
                        'solution':str(s['Solution label (provisional)']),'summary':clean(s.get('Solution description (source)')) or '',
                        'origin_country':COUNTRIES.get((origin or '').lower()),'origin_label':origin,
                        'headquarters_country':None,'product_url':website,'company_website':website,
                        'material_ai_description':None,'maturity':'unknown','technologies':tech,'use_cases':uses,
                        'customer_segments':[clean(s.get('Target customer'))] if clean(s.get('Target customer')) else [],
                        'source_category':clean(s.get('Source solution category')),
                        'source_use_cases':clean(s.get('Source use cases')),
                        'source_technology':raw_tech,
                        'source_urls':[website] if website else [],
                        'singapore_entity':None,'singapore_reseller':None,'singapore_support':None,'singapore_presence':None,
                        'psg_current':None,'psg_status':'unknown','psg_verified_at':None,
                        'price_tier':None,'publication_status':'staging','ai_eligibility':'pending_verification',
                        'source_references':clean(s.get('Source references')),
                        'local_presence_claim':clean(p.get('Source local presence claim')),
                        'historical_psg_claim':clean(g.get('Historical PSG claim')),
                        'verified_source_urls':[]}
                    # Never promote imported or suggested claims into verified status.
                    rows.append(row)
                self.rows=rows;self.by_id={r['solution_id']:r for r in rows}
                countries=sorted({(r['origin_country'],r['origin_country']) for r in rows if r['origin_country']})
                self.tax={**tax,'countries':[{'code':c,'label':label} for c,label in countries],
                          'customer_segments':[]}
                self.stamp=stamp
            finally:wb.close()
    def all(self):self.refresh();return list(self.rows)
    def get(self,sid):self.refresh();return self.by_id.get(sid)
    def taxonomy(self):self.refresh();return self.tax

    @staticmethod
    def matches(row,predicate):
        f=predicate.field;op=predicate.op;values=predicate.values
        value=row.get(f)
        if f=='technology':value=row['technologies']
        elif f=='use_case':value=row['use_cases']
        elif f=='customer_segment':value=row['customer_segments']
        elif f=='company_name':value=row['company']
        elif f=='solution_name':value=row['solution']
        if value is None or value==[]:return None
        fields=value if isinstance(value,list) else [value]
        normalized=[code(v) for v in fields]
        targets=[code(v) for v in values]
        if f=='use_case':
            normalized += [code(row.get('source_use_cases') or '')]
        if f=='technology':normalized += [code(row.get('source_category') or '')]
        equal=any(a==b or (f in ('use_case','technology') and (a.startswith(b+'_') or b.startswith(a+'_'))) for a in normalized for b in targets)
        contained=any(b in a for a in normalized for b in targets)
        if op in ('eq','in'):return equal
        if op=='contains':return contained
        if op=='not_in':return not equal
        if op=='not_contains':return not contained
        return False

    def filter(self,groups):
        confirmed=[];unknown=[];excluded=[]
        for r in self.all():
            unknown_fields=[];failed=[]
            for group in groups:
                vals=[self.matches(r,p) for p in group.any_of]
                if True in vals:continue
                if None in vals:unknown_fields += [p.field for p,v in zip(group.any_of,vals) if v is None]
                else:failed += [p.field for p in group.any_of]
            if failed:excluded.append((r,failed))
            elif unknown_fields:unknown.append((r,sorted(set(unknown_fields))))
            else:confirmed.append(r)
        return confirmed,unknown,excluded
