from pydantic import BaseModel

from models import FixFailureReason, FixVerificationStatus


class VerifierOutput(BaseModel):
    verification_status: FixVerificationStatus
    failure_reason: FixFailureReason | None = None
    retry_count: int = 0
