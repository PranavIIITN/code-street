"""Pydantic request and response models."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class GovernanceDecision(BaseModel):
    allowed: bool
    reason: str


class ActionRequest(BaseModel):
    agent_id: str
    action: str
    amount: float = 0.0
    resource: Optional[str] = None
    risk_score: float = Field(0.0, ge=0.0, le=1.0)


class CapUpdate(BaseModel):
    per_txn_cap: Optional[float] = Field(None, ge=0)
    daily_cap: Optional[float] = Field(None, ge=0)


class PolicyInstruction(BaseModel):
    instruction: str = Field(..., min_length=1)


class PolicyDiff(BaseModel):
    agent_id: Optional[str] = None
    change_type: Literal["update_cap", "update_allowed_actions", "unrecognized"]
    cap_type: Optional[Literal["per_txn", "daily"]] = None
    new_value: Optional[float] = None
    add_actions: Optional[list[str]] = None
    remove_actions: Optional[list[str]] = None
    confidence: Literal["high", "medium", "low"]
    explanation: str
    instruction: Optional[str] = None


class PolicyParseResponse(BaseModel):
    diff: PolicyDiff
    before: Optional[dict] = None
    after: Optional[dict] = None
    preview: Optional[str] = None
    applicable: bool
    warning: Optional[str] = None


class PolicyApplyRequest(BaseModel):
    confirmed: bool
    instruction: str
    diff: PolicyDiff
