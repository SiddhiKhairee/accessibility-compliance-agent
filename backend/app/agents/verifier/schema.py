from pydantic import BaseModel


class VerifierOutput(BaseModel):
    # Phase 2 structural stub only — no real DOM re-check, no LLM call.
    # Phase 3's Verifier fills this in with the real apply-fix-and-reverify
    # logic (docs/schema.md's fixes.verification_status/failure_reason).
    status: str = "pending_verification"
