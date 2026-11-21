from pydantic import BaseModel,Field
from .constants import FieldStrength

class LabelInput(BaseModel):
    visit_id:int
    strength:FieldStrength
    note:str=Field(default='',max_length=300)

class BacktestInput(BaseModel):
    early_ratio:float=Field(default=0.5,gt=0,lt=1)
    false_positive_cap:int=Field(ge=0)

class BacktestRetry(BaseModel):
    note:str=Field(default='',max_length=300)
