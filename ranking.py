from functools import lru_cache
import numpy as np
from .models import Predicate

@lru_cache(maxsize=1)
def encoder():
    from sentence_transformers import SentenceTransformer
    import os
    return SentenceTransformer(os.getenv('EMBEDDING_MODEL','sentence-transformers/all-MiniLM-L6-v2'))

def rank(rows,problem,preferences):
    if not rows:return []
    similarities=[0.0]*len(rows)
    if problem.strip():
        texts=[r.get('search_text') or r.get('summary') or r['solution'] for r in rows]
        vec=encoder().encode([problem]+texts,normalize_embeddings=True)
        similarities=[max(0.0,float(np.dot(vec[0],v))) for v in vec[1:]]
    ranked=[]
    for i,r in enumerate(rows):
        reasons=[];limitations=[];pref=0
        for p in preferences:
            if p.field=='price_tier':
                limitations.append('Pricing is not verified; affordability cannot be ranked yet')
                continue
            if p.field=='origin_country' and r.get('origin_country') in p.values:pref+=1;reasons.append('Preferred origin matches')
            elif p.field=='maturity' and r.get('maturity') in p.values:pref+=1;reasons.append('Preferred maturity matches')
            else:limitations.append(f'Preference {p.field} not verified by ranking')
        score=round(100*(0.85*similarities[i]+0.15*(pref/max(1,len(preferences)))) if problem.strip() else 50+min(pref,3)*10,1)
        if problem.strip():reasons.insert(0,f'Semantic problem similarity: {similarities[i]:.2f}')
        else:reasons.insert(0,'Meets all verified structured filters')
        ranked.append((score,r,reasons,limitations))
    return sorted(ranked,key=lambda x:(-x[0],x[1]['company'],x[1]['solution']))
