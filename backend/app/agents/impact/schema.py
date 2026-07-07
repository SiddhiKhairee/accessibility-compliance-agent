from pydantic import BaseModel, Field


class ImpactOutput(BaseModel):
    is_critical_path: bool
    business_risk_score: float = Field(ge=0, le=1)
    reasoning_text: str
