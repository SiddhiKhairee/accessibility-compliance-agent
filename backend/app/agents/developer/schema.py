from pydantic import BaseModel


class DeveloperOutput(BaseModel):
    proposed_code_diff: str
    target_selector: str
