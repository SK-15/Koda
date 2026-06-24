from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    description: str = Field(description="One concrete, verifiable step toward the goal.")


class Plan(BaseModel):
    steps: list[PlanStep] = Field(description="Ordered steps to accomplish the user's request.")