"""Guarded local operator CLI; never registered as a model/Agent tool."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictInt
from app.host_evidence import build_evidence_catalog
from app.schemas import Soup
from .authoring import CatalogBundle
from .contracts import DatasetError, StrictDatasetModel, validate_reviewed_case
from .grouping import GroupAudit
from .inventory import DatasetInventory, inventory
from .legacy import _read_copy, checked_path
from .manifest import (CaseBundle, _write_new, freeze_dataset, load_repair_corpus,
    read_case_bundle, read_snapshot, write_new_case_bundle, write_new_snapshot)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown argv, which can contain private data.
        raise DatasetError("dataset_cli_arguments_invalid")


class InventoryReport(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    status: Literal["ready", "needs_human"]
    inventory: DatasetInventory
    sourceIssueCount: Annotated[StrictInt, Field(ge=0, le=10000)]


def _parser():
    parser = SafeParser(description="Explicit private offline evaluation data; no model calls.")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("inventory", "freeze"):
        action = actions.add_parser(name)
        for key in ("input", "catalog", "audit", "output"):
            action.add_argument("--" + key, required=True)
    action = actions.add_parser("repair-export")
    action.add_argument("--input", required=True)
    action.add_argument("--output", required=True)
    action.add_argument("--public-synthetic", action="store_true")
    return parser


def _paths(args):
    inputs = tuple(checked_path(Path(value)) for value in
        ([args.input] if args.action == "repair-export" else [args.input, args.catalog, args.audit]))
    output = checked_path(Path(args.output))
    if output.exists() or output in inputs:
        raise DatasetError("dataset_output_exists")
    if len(set(inputs)) != len(inputs):
        raise DatasetError("dataset_input_overlap")
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in inputs):
        raise DatasetError("dataset_output_overlap")
    return inputs, output


def _status(status, counted=None, *, code=None):
    result = {"status": status}
    if code is not None: result["code"] = code
    if counted is not None:
        result.update(inputCount=counted.inputCount, pendingCount=counted.pendingCount,
            reviewedCount=counted.reviewedCount, eligibleCount=counted.eligibleCount)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


def main(argv=None):
    try:
        argv = sys.argv[1:] if argv is None else argv
        if type(argv) is not list or len(argv) > 32 or any(type(v) is not str or len(v) > 2048 for v in argv):
            raise DatasetError("dataset_cli_arguments_invalid")
        args = _parser().parse_args(argv)
        paths, output = _paths(args)
        if args.action == "repair-export":
            snapshot = read_snapshot(paths[0])
            cases = load_repair_corpus(snapshot)
            if args.public_synthetic:
                if any(c.origin != "public_synthetic" or c.visibility != "public_authorized" for c in cases):
                    raise DatasetError("dataset_public_export_forbidden")
            elif snapshot.manifest.visibility != "private":
                raise DatasetError("dataset_public_export_confirmation_required")
            write_new_case_bundle(CaseBundle(cases=cases, sourceDigests=snapshot.manifest.sourceDigests, issues=()), output=output)
            _status("ready")
            return 0
        bundle = read_case_bundle(paths[0])
        catalog = CatalogBundle.model_validate_json(_read_copy(paths[1])).puzzles
        audit = GroupAudit.model_validate_json(_read_copy(paths[2]))
        counted = inventory(bundle.cases, audit=audit, source_digests=bundle.sourceDigests)
        scopes = {(p.soupId, p.puzzleVersion): {r.id for r in build_evidence_catalog(
            Soup.model_validate_json(p.soupJson), p.puzzleVersion)} for p in catalog}
        for case in bundle.cases:
            facts = scopes.get((case.soupId, case.puzzleVersion))
            if facts is None or not set(case.proposedFactIds) <= facts:
                raise DatasetError("dataset_catalog_scope_invalid")
        # Counts of declarations alone are not evidence of source-bound review.
        for case in bundle.cases:
            if case.reviewState == "reviewed":
                validate_reviewed_case(case, catalog=catalog, context_cases=bundle.cases)
        ready = (bool(bundle.cases) and counted.eligibleCount == counted.inputCount
            and counted.auditComplete and not counted.issueCount and not bundle.issues
            and not any(counted.deficits.model_dump().values()))
        if args.action == "freeze" and any(c.split not in {"holdout_candidate", "holdout"}
            or c.origin != "new_authoring" or c.visibility != "private" for c in bundle.cases):
            raise DatasetError("dataset_holdout_role_invalid")
        status = "ready" if ready else "needs_human"
        if args.action == "freeze" and ready:
            snapshot = freeze_dataset(bundle.cases, catalog=catalog, audit=audit,
                source_digests=bundle.sourceDigests, frozen_at=datetime.now(timezone.utc).isoformat())
            write_new_snapshot(snapshot, output=output)
        else:
            # A raw physical issue is preserved even when a separately provided
            # audit incorrectly claims complete. No formal seal is produced.
            report = InventoryReport(status=status, inventory=counted, sourceIssueCount=len(bundle.issues))
            _write_new(report, output)
        _status(status, counted)
        return 0 if ready else 2
    except DatasetError as error:
        _status("refused", code=error.code)
        return 1
    except Exception:
        _status("refused", code="dataset_cli_refused")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
