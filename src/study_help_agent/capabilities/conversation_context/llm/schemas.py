from pydantic import BaseModel, Field


class SessionSummaryOutput(BaseModel):
    summary: str = Field(
        min_length=1,
        max_length=3000,
    )