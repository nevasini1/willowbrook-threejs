from pydantic import BaseModel
from typing import List, Optional


class ChatRequest(BaseModel):
    agent_id: str
    message: str


class ChatResponse(BaseModel):
    agent_id: str
    reply: str


class InnerVoiceRequest(BaseModel):
    agent_id: str
    command: str


class InnerVoiceResponse(BaseModel):
    agent_id: str
    result: str


class TickRequest(BaseModel):
    agent_id: Optional[str] = None  # None means tick all agents


class TickResult(BaseModel):
    agent_id: str
    action: str
    success: bool
    detail: str = ""


class TickResponse(BaseModel):
    results: List[TickResult]
