from dataclasses import dataclass,field
from threading import RLock
from uuid import uuid4
from .models import QueryPlan,FilterGroup,Predicate

@dataclass
class Session:
    id: str
    plan: QueryPlan=field(default_factory=QueryPlan)
    last_ids: list[str]=field(default_factory=list)

class MemorySessions:
    # Development only; use Redis with TTL, locking and privacy controls in production.
    def __init__(self): self.data={};self.lock=RLock()
    def get(self,session_id=None):
        with self.lock:
            if session_id and session_id in self.data: return self.data[session_id]
            s=Session(id=str(uuid4()));self.data[s.id]=s;return s

def merge(old:QueryPlan,new:QueryPlan)->QueryPlan:
    if new.operation in ('replace','reset'): return new
    d=old.model_copy(deep=True)
    if new.operation=='remove':
        fields=set(new.remove_fields)
        d.hard=[FilterGroup(any_of=[p for p in g.any_of if p.field not in fields]) for g in d.hard if any(p.field not in fields for p in g.any_of)]
        d.preferences=[p for p in d.preferences if p.field not in fields]
    else:
        changed={p.field for g in new.hard for p in g.any_of}|{p.field for p in new.preferences}
        d.hard=[FilterGroup(any_of=[p for p in g.any_of if p.field not in changed]) for g in d.hard if any(p.field not in changed for p in g.any_of)]
        d.preferences=[p for p in d.preferences if p.field not in changed]
        d.hard+=new.hard;d.preferences+=new.preferences
    d.intent=new.intent;d.problem=new.problem or d.problem;d.compare_positions=new.compare_positions;d.clarification=new.clarification
    return d
