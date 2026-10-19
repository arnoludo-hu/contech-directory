from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, model_validator

FieldName = Literal['origin_country','headquarters_country','singapore_presence','singapore_entity','singapore_reseller','singapore_support','psg_current','technology','use_case','customer_segment','maturity','price_tier','company_name','solution_name']
Op = Literal['eq','in','not_in','contains','not_contains']

class Predicate(BaseModel):
    field: FieldName
    op: Op = 'eq'
    values: list[str] = Field(min_length=1,max_length=30)
    @model_validator(mode='after')
    def validate_values(self):
        if self.field in ('singapore_presence','singapore_entity','singapore_reseller','singapore_support','psg_current'):
            if self.op not in ('eq','in','not_in') or any(v not in ('true','false') for v in self.values):
                raise ValueError('Boolean filters require true/false')
        if self.field in ('origin_country','headquarters_country') and any(len(v)!=2 or not v.isalpha() for v in self.values):
            raise ValueError('Use ISO-2 country codes')
        return self

class FilterGroup(BaseModel):
    # AND across groups, OR across any_of within each group; NOT via not_in/not_contains
    any_of: list[Predicate] = Field(min_length=1,max_length=15)

class QueryPlan(BaseModel):
    intent: Literal['discover','count','list','compare','lookup','refine'] = 'discover'
    operation: Literal['replace','add','remove','reset'] = 'replace'
    problem: str = ''
    hard: list[FilterGroup] = Field(default_factory=list,max_length=20)
    preferences: list[Predicate] = Field(default_factory=list,max_length=20)
    remove_fields: list[FieldName] = Field(default_factory=list)
    compare_positions: list[int] = Field(default_factory=list)
    clarification: str | None = None
    @model_validator(mode='after')
    def check_compare(self):
        if self.intent=='compare' and not self.compare_positions:
            raise ValueError('Comparison needs result positions')
        return self

class SearchRequest(BaseModel):
    message: str = Field(min_length=1,max_length=2000)
    session_id: str | None = None
    page: int = Field(default=1,ge=1)
    page_size: int = Field(default=10,ge=1,le=100)

class EvidenceItem(BaseModel):
    field: str
    excerpt: str
    status: str

class Match(BaseModel):
    solution_id: str
    company_id: str
    company: str
    solution: str
    score: float
    reasons: list[str]
    limitations: list[str]
    source_urls: list[str]
    matched_fields: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    verification_status: str = "imported_unverified"
    origin_country: str | None = None
    origin_label: str | None = None
    use_cases: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    psg_status: str = "unknown"
    singapore_presence_status: str = "unknown"

class SearchResponse(BaseModel):
    session_id: str
    intent: str
    applied_filters: list[FilterGroup]
    preferences: list[Predicate]
    total_solutions: int
    total_companies: int
    page: int
    page_size: int
    matches: list[Match]
    unverified_count: int = 0
    clarification: str | None = None
    message: str = ''
