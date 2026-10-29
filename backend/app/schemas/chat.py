"""Validated single-question chat input and output."""

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Reject blank questions and bound input size before calling the model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=10000)


class ChatResponse(BaseModel):
    """One complete model-generated answer."""

    answer: str
