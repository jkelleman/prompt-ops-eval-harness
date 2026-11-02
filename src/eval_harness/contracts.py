"""Pydantic v2 contracts for agent-generated lakehouse execution plans.

Every plan an agent proposes must validate against these models before it can
run. Anything the model invents that the contract doesn't allow is rejected
at the boundary instead of reaching Spark.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WriteMode(str, Enum):
    APPEND = "append"
    MERGE = "merge"
    OVERWRITE = "overwrite"
    DROP_PARTITION = "drop_partition"

    @property
    def is_destructive(self) -> bool:
        """Destructive writes require an explicit human approval gate."""
        return self in (WriteMode.OVERWRITE, WriteMode.DROP_PARTITION)


class AgentExecutionState(str, Enum):
    """The six states an autonomous run moves through."""

    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING_REMOTE = "running_remote"
    HEALING = "healing"
    VERIFIED = "verified"
    FAILED = "failed"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PreCommitAssertion(StrictModel):
    """A check that must pass before a write is committed."""

    name: str = Field(min_length=1)
    kind: Literal["row_count_min", "not_null", "partition_exists"]
    column: str | None = None
    threshold: int | None = Field(default=None, ge=0)

    @field_validator("column")
    @classmethod
    def _column_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("column must not be blank")
        return v


class LakehouseExecutionPlan(StrictModel):
    task_id: str = Field(min_length=1)
    target_lakehouse: str = Field(min_length=1)
    target_table: str = Field(min_length=1)
    write_mode: WriteMode
    columns: list[str] = Field(min_length=1)
    assertions: list[PreCommitAssertion] = Field(min_length=1)

    @property
    def requires_approval(self) -> bool:
        return self.write_mode.is_destructive

    @property
    def qualified_table(self) -> str:
        return f"{self.target_lakehouse}.{self.target_table}"


class RemediationAction(StrictModel):
    """An in-memory code patch proposed by the self-healing interceptor."""

    kind: Literal["cast_column"]
    column: str
    from_type: str
    to_type: str
    patch_before: str
    patch_after: str


class AgentRecoveryEnvelope(StrictModel):
    """What the runtime reports after catching a failure."""

    task_id: str
    error_type: str
    error_message: str
    attempt: int = Field(ge=1)
    state: AgentExecutionState
    remediation: RemediationAction | None = None
