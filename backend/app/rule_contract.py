"""Immutable exact-rule proof and suspension fence; no publication authority."""
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .baselines import SnapshotError, strict_json
from .question_normalization import normalize_exact_question
from .schemas import AnswerType
from .audit_events import CanonicalId

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
PuzzleVersion = Annotated[str, Field(pattern=r"^p1:[0-9a-f]{64}$", min_length=67, max_length=67)]
RuleVersion = Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
FactId = Annotated[str, Field(pattern=r"^f1:[0-9a-f]{64}$", min_length=67, max_length=67)]


class StrictRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class PublishedExactRule(StrictRuleModel):
    schemaVersion: Literal[1] = 1
    type: Literal["exact_qa"] = "exact_qa"
    op: Literal["add", "replace"]
    canonicalQuestionKey: Annotated[str, Field(min_length=1, max_length=500)]
    question: Annotated[str, Field(min_length=1, max_length=500)]
    normalizationVersion: Literal["exact-v1"] = "exact-v1"
    answer: AnswerType
    factIds: Annotated[tuple[FactId, ...], Field(min_length=1, max_length=256)]
    targetRuleDigest: Digest | None = None
    puzzleVersion: PuzzleVersion
    baseRuleVersion: RuleVersion
    candidateDigest: Digest
    reportDigest: Digest
    confirmedContext: Literal[True]
    reviewReceipt: "ReviewReceipt"

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unknown exact-rule schema")
        return value

    @field_validator("confirmedContext", mode="before")
    @classmethod
    def real_confirmation(cls, value):
        if value is not True:
            raise ValueError("Independent context confirmation required")
        return value

    @model_validator(mode="after")
    def consistent_exact_rule(self):
        if self.canonicalQuestionKey != normalize_exact_question(self.question):
            raise ValueError("Exact key mismatch")
        if len(set(self.factIds)) != len(self.factIds):
            raise ValueError("Duplicate fact identity")
        if (self.op == "replace") != (self.targetRuleDigest is not None):
            raise ValueError("Exact operation target mismatch")
        from .baselines import digest
        draft = {name: getattr(self, name) for name in ChangeDraft.model_fields}
        # JSON shape uses arrays, and digest() canonicalizes tuples as arrays.
        receipt = self.reviewReceipt
        if (receipt.draftDigest != digest(draft) or receipt.candidateDigest != self.candidateDigest
            or receipt.reportDigest != self.reportDigest or receipt.puzzleVersion != self.puzzleVersion
            or receipt.baseRuleVersion != self.baseRuleVersion
            or not receipt.answerSupported or not receipt.contextIndependent):
            raise ValueError("Published rule and review proof disagree")
        return self


class RuleSnapshot(StrictRuleModel):
    ruleVersion: RuleVersion
    puzzleVersion: PuzzleVersion
    soupId: Annotated[str, Field(min_length=1, max_length=200)]
    exactRules: Annotated[tuple[PublishedExactRule, ...], Field(max_length=1000)]
    # Full immutable proof, not only this soup's mutable projection. Host will
    # revalidate the content-addressed r1 against pinned versions before cache.
    releaseRulesJson: Annotated[str, Field(min_length=1, max_length=2097152)]
    releaseManifestJson: Annotated[str, Field(min_length=1, max_length=2097152)]


class ChangeDraft(StrictRuleModel):
    op: Literal["add", "replace"]
    canonicalQuestionKey: Annotated[str, Field(min_length=1, max_length=500)]
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: AnswerType
    factIds: Annotated[tuple[FactId, ...], Field(min_length=1, max_length=256)]
    targetRuleDigest: Digest | None = None
    puzzleVersion: PuzzleVersion
    baseRuleVersion: RuleVersion
    confirmedContext: Literal[True]

    @field_validator("confirmedContext", mode="before")
    @classmethod
    def manual_confirmation(cls, value):
        if value is not True:
            raise ValueError("Context confirmation required")
        return value

    @model_validator(mode="after")
    def exact_change(self):
        if self.canonicalQuestionKey != normalize_exact_question(self.question) or len(set(self.factIds)) != len(self.factIds):
            raise ValueError("Invalid exact change")
        if self.op == "add" and self.targetRuleDigest is not None:
            raise ValueError("Add must not target an existing rule")
        # Missing/ambiguous replacement target is a controlled needs-human
        # business refusal, not permission to invent the target here.
        return self


PointerVersion = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]


class PublicationRequest(StrictRuleModel):
    operationKey: CanonicalId
    expectedRuleVersion: RuleVersion
    expectedPointerVersion: PointerVersion
    changeDraft: ChangeDraft
    regressionReportId: CanonicalId
    candidateDigest: Digest


class ReviewReceipt(StrictRuleModel):
    draftDigest: Digest
    candidateDigest: Digest
    regressionReportId: CanonicalId
    reportDigest: Digest
    suiteManifestDigest: Digest
    puzzleVersion: PuzzleVersion
    baseRuleVersion: RuleVersion
    status: Literal["complete"]
    answerSupported: bool
    contextIndependent: bool
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]


class RulePublicationResult(StrictRuleModel):
    operationKey: CanonicalId
    ruleVersion: RuleVersion
    pointerVersion: PointerVersion
    markerVersion: PointerVersion | None = None


class SuspensionRequest(StrictRuleModel):
    operationKey: CanonicalId
    ruleVersion: RuleVersion
    expectedMarkerVersion: PointerVersion | None
    suspended: bool
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class RollbackRequest(StrictRuleModel):
    operationKey: CanonicalId
    targetRuleVersion: RuleVersion
    expectedRuleVersion: RuleVersion
    expectedPointerVersion: PointerVersion
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    blockRuleVersion: RuleVersion | None = None

    @model_validator(mode="after")
    def only_block_source(self):
        if self.blockRuleVersion is not None and (self.blockRuleVersion != self.expectedRuleVersion
            or self.blockRuleVersion == self.targetRuleVersion):
            raise ValueError("Rollback may block only its old source, never the active target")
        return self


class ExactTarget(StrictRuleModel):
    targetRuleDigest: Digest
    type: Literal["exact_qa", "confusion"]
    sourcePath: Annotated[str, Field(min_length=1, max_length=200)]


def _validate_schema2(conn, rules, manifest, parent_id):
    """Validate ALL soup overlays; an unused corrupt soup is not an intact release."""
    from . import baselines
    from .host_evidence import build_evidence_catalog
    from .host_rules import question_has_static_scope
    if (type(rules) is not dict or set(rules) != {"schemaVersion", "rulesBySoup", "exactQaBySoup"}
        or type(rules["schemaVersion"]) is not int or rules["schemaVersion"] != 2
        or type(manifest) is not dict
        or set(manifest) != {"schemaVersion", "puzzleVersions", "origin", "parentRuleVersion"}
        or type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 2
        or manifest["origin"] != "reviewed-exact-rule"
        or parent_id != manifest["parentRuleVersion"] or not isinstance(parent_id, str)
        or not re.fullmatch(r"r1:[0-9a-f]{64}", parent_id)):
        raise ValueError("Unknown exact-rule release schema")
    versions = manifest["puzzleVersions"]
    if (type(versions) is not dict or not versions or type(rules["rulesBySoup"]) is not dict
        or type(rules["exactQaBySoup"]) is not dict or set(versions) != set(rules["rulesBySoup"])
        or set(versions) != set(rules["exactQaBySoup"])):
        raise ValueError("Exact-rule catalog mismatch")
    # No recursive walk of an arbitrarily deep historical chain. Immediate
    # parent proof and each referenced base's original p1 fields are checked.
    bases = {}

    def base(version):
        if version not in bases:
            row = conn.execute("SELECT rules_json,manifest_json FROM rule_releases WHERE id=?", (version,)).fetchone()
            if row is None:
                raise ValueError("Missing source rule release")
            old_rules, old_manifest = strict_json(row[0]), strict_json(row[1])
            if (type(old_rules) is not dict or type(old_manifest) is not dict
                or "r1:" + baselines.digest({"rules": old_rules, "manifest": old_manifest}) != version
                or type(old_rules.get("schemaVersion")) is not int or old_rules["schemaVersion"] not in {1, 2}
                or old_manifest.get("puzzleVersions") != versions
                or old_rules.get("rulesBySoup") != rules["rulesBySoup"]):
                raise ValueError("Changed source puzzle or invalid base")
            bases[version] = (old_rules, old_manifest)
        return bases[version]

    base(parent_id)
    for soup_id, p1 in versions.items():
        soup = baselines.session_soup(conn, p1)
        expected = {name: soup.model_dump(mode="json")[name] for name in baselines.RULE_FIELDS}
        if soup.id != soup_id or rules["rulesBySoup"][soup_id] != expected:
            raise ValueError("Changed original puzzle rules")
        raw = rules["exactQaBySoup"][soup_id]
        if type(raw) is not list or len(raw) > 1000:
            raise ValueError("Invalid exact-rule list")
        facts = {record.id for record in build_evidence_catalog(soup, p1)}
        keys = set()
        for item in raw:
            rule = PublishedExactRule.model_validate_json(baselines.canonical_json(item))
            if (rule.puzzleVersion != p1 or not set(rule.factIds) <= facts
                or rule.canonicalQuestionKey in keys or not question_has_static_scope(soup, rule.question)):
                raise ValueError("Unbound, ambiguous or context-dependent exact rule")
            old_rules, _ = base(rule.baseRuleVersion)
            targets = exact_targets_from_source(soup, p1, rule.baseRuleVersion, old_rules, rule.question)
            if rule.op == "replace":
                if len(targets) != 1 or targets[0].targetRuleDigest != rule.targetRuleDigest:
                    raise ValueError("Replacement source proof mismatch")
            else:
                from .host_rules import decide_deterministic
                from .schemas import HostVersions
                if targets or decide_deterministic(soup, rule.question, [], versions=HostVersions(
                    puzzleVersion=p1, ruleVersion=rule.baseRuleVersion)) is not None:
                    raise ValueError("Add conflicts with original rule")
            keys.add(rule.canonicalQuestionKey)


def exact_targets_from_source(soup, puzzle_version, rule_version, rules, question):
    """Complete current-source identity; shared with publication and read validation."""
    from .baselines import canonical_json, digest
    from .host_rules import question_has_static_scope
    if not question_has_static_scope(soup, question):
        return ()
    key = normalize_exact_question(question)
    exact = [PublishedExactRule.model_validate_json(canonical_json(raw))
        for raw in rules.get("exactQaBySoup", {}).get(soup.id, [])
        if raw["canonicalQuestionKey"] == key]
    if exact:
        return tuple(ExactTarget(type="exact_qa", sourcePath="exactQaBySoup:" + soup.id,
            targetRuleDigest=digest(rule.model_dump(mode="json"))) for rule in exact)
    targets = []
    for index, item in enumerate(soup.confusionPoints or ()):
        if question_has_static_scope(soup, item.q) and normalize_exact_question(item.q) == key:
            path = f"confusionPoints[{index}]"
            proof = dict(type="confusion", sourcePath=path, sourcePayload=item.model_dump(mode="json"),
                puzzleVersion=puzzle_version, baseRuleVersion=rule_version, normalizationVersion="exact-v1")
            targets.append(ExactTarget(type="confusion", sourcePath=path, targetRuleDigest=digest(proof)))
    return tuple(targets)


def read_rule_snapshot(conn, puzzle_version, rule_version):
    """Owned connection/snapshot belongs to caller; never writes or chooses a pointer."""
    from . import baselines
    try:
        soup = baselines.session_baseline(conn, puzzle_version, rule_version)
        rules, manifest = baselines._rule_release(conn, rule_version)
        raw = rules.get("exactQaBySoup", {}).get(soup.id, [])
        exact = tuple(PublishedExactRule.model_validate_json(baselines.canonical_json(item)) for item in raw)
        return RuleSnapshot(ruleVersion=rule_version, puzzleVersion=puzzle_version, soupId=soup.id,
            exactRules=exact, releaseRulesJson=baselines.canonical_json(rules),
            releaseManifestJson=baselines.canonical_json(manifest))
    except Exception:
        raise SnapshotError("Invalid exact-rule snapshot") from None


def verify_rule_snapshot(snapshot, soup, versions):
    """Recheck a projection AND full r1 proof before any host/cache authority."""
    from . import baselines
    from .host_evidence import build_evidence_catalog, validate_puzzle_snapshot
    from .host_rules import question_has_static_scope
    try:
        checked = RuleSnapshot.model_validate_json(snapshot.model_dump_json())
        validate_puzzle_snapshot(soup, versions.puzzleVersion)
        if (checked.soupId != soup.id or checked.puzzleVersion != versions.puzzleVersion
            or checked.ruleVersion != versions.ruleVersion
            or len(checked.releaseRulesJson.encode()) > 2097152 or len(checked.releaseManifestJson.encode()) > 2097152):
            raise ValueError("Host snapshot scope mismatch")
        rules, manifest = strict_json(checked.releaseRulesJson), strict_json(checked.releaseManifestJson)
        schema = rules["schemaVersion"]
        if (type(schema) is not int or schema not in {1, 2} or type(manifest["schemaVersion"]) is not int
            or manifest["schemaVersion"] != schema
            or "r1:" + baselines.digest({"rules": rules, "manifest": manifest}) != checked.ruleVersion
            or set(rules) != ({"schemaVersion", "rulesBySoup"} if schema == 1 else
                {"schemaVersion", "rulesBySoup", "exactQaBySoup"})
            or set(manifest) != ({"schemaVersion", "puzzleVersions", "origin"} if schema == 1 else
                {"schemaVersion", "puzzleVersions", "origin", "parentRuleVersion"})
            or manifest["puzzleVersions"].get(soup.id) != checked.puzzleVersion
            or rules["rulesBySoup"].get(soup.id) != {name: soup.model_dump(mode="json")[name] for name in baselines.RULE_FIELDS}):
            raise ValueError("Host proof mismatch")
        raw = rules.get("exactQaBySoup", {}).get(soup.id, [])
        actual = tuple(PublishedExactRule.model_validate_json(baselines.canonical_json(item)) for item in raw)
        facts = {record.id for record in build_evidence_catalog(soup, checked.puzzleVersion)}
        if (checked.exactRules != actual or len({rule.canonicalQuestionKey for rule in actual}) != len(actual)
            or any(rule.puzzleVersion != checked.puzzleVersion or not set(rule.factIds) <= facts
                or not question_has_static_scope(soup, rule.question) for rule in actual)):
            raise ValueError("Host overlay differs from frozen proof")
        return checked
    except Exception:
        raise SnapshotError("Invalid host rule snapshot") from None


def rule_suspension_state(conn, rule_version):
    if not isinstance(rule_version, str) or not re.fullmatch(r"r1:[0-9a-f]{64}", rule_version):
        raise SnapshotError("Invalid rule identity")
    row = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key=?",
        ("rule_suspension:" + rule_version[3:],)).fetchone()
    if row is None:
        return False
    try:
        value = strict_json(row[0])
        if (type(value) is not dict or set(value) != {"schemaVersion", "ruleVersion", "suspended", "reason"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
            or value["ruleVersion"] != rule_version or type(value["suspended"]) is not bool
            or not isinstance(value["reason"], str) or not 1 <= len(value["reason"]) <= 1000
            or type(row[1]) is not int or not 0 <= row[1] <= 9223372036854775807):
            raise ValueError("Malformed suspension marker")
        return value["suspended"]
    except Exception:
        raise SnapshotError("Invalid suspension state") from None
