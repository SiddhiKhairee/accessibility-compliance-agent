from pydantic import BaseModel, Field


class ReviewerOutput(BaseModel):
    confirmed: bool
    confidence_score: float = Field(ge=0, le=1)
    reasoning: str
