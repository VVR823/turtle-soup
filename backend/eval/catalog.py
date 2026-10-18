"""Validate explicit immutable catalog proof without database/runtime access."""
from app.baselines import canonical_json, strict_json
from app.host_evidence import validate_puzzle_snapshot
from app.rule_contract import verify_rule_snapshot
from app.schemas import HostVersions, Soup

from .contracts import DatasetError, EvalPuzzle


def _validate_full_release_structure(snapshot):
    """All r1 members' shape; unprovided Soup content is not semantically proven."""
    import re
    from app.baselines import RULE_FIELDS
    from app.rule_contract import PublishedExactRule
    rules, manifest = strict_json(snapshot.releaseRulesJson), strict_json(snapshot.releaseManifestJson)
    if (type(rules) is not dict or type(manifest) is not dict
        or canonical_json(rules) != snapshot.releaseRulesJson
        or canonical_json(manifest) != snapshot.releaseManifestJson):
        raise ValueError("Canonical full release required")
    schema = rules.get("schemaVersion")
    if (type(schema) is not int or schema not in {1, 2}
        or type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != schema
        or set(rules) != ({"schemaVersion", "rulesBySoup"} if schema == 1 else {"schemaVersion", "rulesBySoup", "exactQaBySoup"})
        or set(manifest) != ({"schemaVersion", "puzzleVersions", "origin"} if schema == 1 else
            {"schemaVersion", "puzzleVersions", "origin", "parentRuleVersion"})
        or type(manifest.get("origin")) is not str or not manifest["origin"].strip()
        or len(manifest["origin"]) > 200):
        raise ValueError("Full release schema invalid")
    versions, fragments = manifest["puzzleVersions"], rules["rulesBySoup"]
    if (type(versions) is not dict or not 1 <= len(versions) <= 256
        or type(fragments) is not dict or set(versions) != set(fragments)):
        raise ValueError("Full release membership differs")
    for identity, p1 in versions.items():
        fragment = fragments[identity]
        if (type(identity) is not str or not 1 <= len(identity) <= 200 or not identity.strip()
            or type(p1) is not str or not re.fullmatch(r"p1:[0-9a-f]{64}", p1)
            or type(fragment) is not dict or set(fragment) != set(RULE_FIELDS)):
            raise ValueError("Full release member invalid")
        # Validate nested field shapes without inventing the omitted truth/surface
        # or claiming the external member's full p1 has been reconstructed.
        preview = Soup.model_validate({"id": identity, "title": "Structural proof only",
            "surface": "Unprovided", "bottom": "Unprovided", **fragment})
        typed = {name: preview.model_dump(mode="json")[name] for name in RULE_FIELDS}
        if canonical_json(typed) != canonical_json(fragment):
            raise ValueError("Coerced or incomplete rule member")
    if schema == 2:
        parent, overlays = manifest["parentRuleVersion"], rules["exactQaBySoup"]
        if (manifest["origin"] != "reviewed-exact-rule" or type(parent) is not str
            or not re.fullmatch(r"r1:[0-9a-f]{64}", parent) or parent == snapshot.ruleVersion
            or type(overlays) is not dict or set(overlays) != set(versions)):
            raise ValueError("Full overlay release invalid")
        for identity, raw in overlays.items():
            if type(raw) is not list or len(raw) > 1000:
                raise ValueError("Overlay member bound")
            entries = tuple(PublishedExactRule.model_validate_json(canonical_json(item)) for item in raw)
            if (len({e.canonicalQuestionKey for e in entries}) != len(entries)
                or any(e.puzzleVersion != versions[identity] for e in entries)
                or canonical_json([e.model_dump(mode="json") for e in entries]) != canonical_json(raw)):
                raise ValueError("Overlay member differs")


def build_seed_catalog(*, soup_ids: tuple[str, ...]) -> tuple[EvalPuzzle, ...]:
    """Pure static authoring catalog, explicitly not the production active r1."""
    from app.baselines import RULE_FIELDS
    from app.baselines import digest
    from app.rule_contract import RuleSnapshot
    from app.soups import SEED_SOUPS  # Code-owned literal only; no db/runtime loader.
    try:
        if type(soup_ids) is not tuple or not 1 <= len(soup_ids) <= 256 or len(set(soup_ids)) != len(soup_ids):
            raise DatasetError("dataset_seed_selection_invalid")
        selected = [Soup.model_validate(raw) for raw in SEED_SOUPS if raw.get("id") in soup_ids]
        if {s.id for s in selected} != set(soup_ids):
            raise DatasetError("dataset_seed_selection_invalid")
        selected.sort(key=lambda s: s.id)
        payloads = {s.id: s.model_dump(mode="json") for s in selected}
        versions = {identity: "p1:" + digest({"schemaVersion": 1, "soup": raw}) for identity, raw in payloads.items()}
        rules = {"schemaVersion": 1, "rulesBySoup": {identity: {f: raw[f] for f in RULE_FIELDS} for identity, raw in payloads.items()}}
        manifest = {"schemaVersion": 1, "puzzleVersions": versions, "origin": "eval-seed-snapshot"}
        rule_version = "r1:" + digest({"rules": rules, "manifest": manifest})
        catalog = tuple(EvalPuzzle(soupId=s.id, puzzleVersion=versions[s.id], soupJson=canonical_json(payloads[s.id]),
            ruleSnapshot=RuleSnapshot(soupId=s.id, puzzleVersion=versions[s.id], ruleVersion=rule_version, exactRules=(),
                releaseRulesJson=canonical_json(rules), releaseManifestJson=canonical_json(manifest))) for s in selected)
        return validate_catalog(catalog)
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_seed_selection_invalid") from None


def validate_catalog(puzzles: tuple[EvalPuzzle, ...]) -> tuple[EvalPuzzle, ...]:
    try:
        if type(puzzles) is not tuple or not 1 <= len(puzzles) <= 256:
            raise ValueError("Bounded catalog required")
        checked = tuple(EvalPuzzle.model_validate_json(p.model_dump_json()) for p in puzzles)
        if len({p.soupId for p in checked}) != len(checked) or len({p.puzzleVersion for p in checked}) != len(checked):
            raise ValueError("Duplicate puzzle identity")
        if len(canonical_json([p.model_dump(mode="json") for p in checked]).encode("utf-8")) > 2097152:
            raise ValueError("Catalog proof too large")
        for item in checked:
            raw = strict_json(item.soupJson)
            if not isinstance(raw, dict) or set(raw) != set(Soup.model_fields) or canonical_json(raw) != item.soupJson:
                raise ValueError("Complete canonical puzzle required")
            soup = Soup.model_validate(raw)
            if soup.model_dump(mode="json") != raw or soup.id != item.soupId:
                raise ValueError("Puzzle identity or types differ")
            validate_puzzle_snapshot(soup, item.puzzleVersion)
            _validate_full_release_structure(item.ruleSnapshot)
            verify_rule_snapshot(item.ruleSnapshot, soup,
                HostVersions(puzzleVersion=item.puzzleVersion, ruleVersion=item.ruleSnapshot.ruleVersion))
        return checked
    except Exception:
        raise DatasetError("dataset_catalog_invalid") from None
