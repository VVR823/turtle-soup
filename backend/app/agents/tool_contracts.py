"""Closed read/proof tool results; facts and player claims are not verdicts."""
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from ..audit_events import CanonicalId, Identity
from ..feedback_contract import SanitizedInput
from ..host_evidence import retrieve_evidence, validate_puzzle_snapshot
from ..rule_contract import FactId, PuzzleVersion, RuleVersion
from ..task_context import ProgramDiagnostic
from .contracts import StrictAgentModel, checked_model
from .validation import ConflictResult


class ToolResultBase(StrictAgentModel):
    schemaVersion: Literal[1] = 1

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value


class TraceResult(ToolResultBase):
    tool: Literal["get_turn_trace"] = "get_turn_trace"
    turnId: CanonicalId
    soupId: Identity
    puzzleVersion: PuzzleVersion
    observedRuleVersion: RuleVersion
    baseRuleVersion: RuleVersion
    sanitizedInput: SanitizedInput
    claimsOnly: Literal[True] = True
    programDiagnostic: ProgramDiagnostic

    @field_validator("claimsOnly", mode="before")
    @classmethod
    def not_gold(cls, value):
        if value is not True:
            raise ValueError("Claims are not independently verified labels")
        return value


class FactExcerpt(StrictAgentModel):
    id: FactId
    sourcePath: Annotated[str, Field(min_length=1, max_length=200)]
    category: Literal["truth", "checkpoint", "confusion", "symbol", "metadata"]
    excerpt: Annotated[str, Field(min_length=1, max_length=256)]
    truncated: bool


class TruthResult(ToolResultBase):
    tool: Literal["retrieve_truth"] = "retrieve_truth"
    soupId: Identity
    puzzleVersion: PuzzleVersion
    facts: Annotated[tuple[FactExcerpt, ...], Field(max_length=8)]

    @model_validator(mode="after")
    def unique_hits(self):
        if len({f.id for f in self.facts}) != len(self.facts):
            raise ValueError("Duplicate retrieved fact")
        return self


class ConflictToolResult(ToolResultBase):
    tool: Literal["find_rule_conflicts"] = "find_rule_conflicts"
    conflict: ConflictResult


ToolSuccess = Annotated[TraceResult | TruthResult | ConflictToolResult, Field(discriminator="tool")]
_SUCCESS = TypeAdapter(ToolSuccess)


def checked_tool_success(value):
    class Boundary:
        model_validate_json = staticmethod(_SUCCESS.validate_json)
    return checked_model(Boundary, value)


def trace_result(context):
    return TraceResult(turnId=context.turnId, soupId=context.soupId, puzzleVersion=context.observedPuzzleVersion,
        observedRuleVersion=context.observedRuleVersion, baseRuleVersion=context.baseRuleVersion,
        sanitizedInput=context.sanitizedInput, programDiagnostic=context.programDiagnostic)


def truth_result(soup, context, query):
    validate_puzzle_snapshot(soup, context.observedPuzzleVersion)
    if soup.id != context.soupId:
        raise ValueError("Foreign truth source")
    allowed = {f.id for f in context.factScope}
    records = retrieve_evidence(soup, query, puzzle_version=context.observedPuzzleVersion, limit=8)
    return TruthResult(soupId=context.soupId, puzzleVersion=context.observedPuzzleVersion,
        facts=tuple(FactExcerpt(id=f.id, sourcePath=f.sourcePath, category=f.category,
            excerpt=f.payload[:256], truncated=len(f.payload) > 256) for f in records if f.id in allowed))
