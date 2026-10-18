"""Explicit private offline CLI; fixed fake drivers, no cloud or implicit input."""
import json
import argparse
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from app.baselines import digest
from app.schemas import AnswerType, HOST_ENGINE_VERSION
from .contracts import DatasetError, StrictDatasetModel
from .legacy import _read_copy, checked_path
from .manifest import _write_new, read_snapshot
from .run_contracts import RunBudget, RunReport, SystemSpec, verify_run_report

ANSWERS = ("是", "不是", "是也不是", "算是", "与此无关")
MAX_BYTES = 100 * 1024 * 1024


class RunBundle(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    reports: Annotated[tuple[RunReport, ...], Field(min_length=1, max_length=10)]


def verify_run_bundle(bundle: RunBundle) -> RunBundle:
    try:
        raw = bundle.model_dump_json(warnings="error")
        if len(raw.encode("utf-8")) > MAX_BYTES: raise DatasetError("eval_bundle_limit")
        checked = RunBundle.model_validate_json(raw)
        reports = tuple(verify_run_report(r) for r in checked.reports)
        first = reports[0].manifest
        if (len(reports) != first.repeatCount
            or tuple(sorted(r.manifest.repeatIndex for r in reports)) != tuple(range(first.repeatCount))
            or len({r.manifest.runId for r in reports}) != len(reports)):
            raise DatasetError("eval_bundle_repetitions_invalid")
        fields = ("datasetDigest", "puzzleVersions", "ruleVersions", "inputCaseIds", "inputCount", "system",
            "repeatCount", "runnerVersion", "metricsVersion", "attemptAccounting")
        if any(any(getattr(r.manifest, field) != getattr(first, field) for field in fields) for r in reports):
            raise DatasetError("eval_bundle_scope_mismatch")
        return RunBundle(reports=reports)
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_bundle_invalid") from None


def read_run_bundle(path: Path) -> RunBundle:
    try:
        return verify_run_bundle(RunBundle.model_validate_json(_read_copy(checked_path(path))))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_bundle_invalid") from None


def _offline_driver(name: str, *, data_dir: Path, answer: AnswerType):
    from app.config import Settings
    from app.testing import FakeModel
    from .drivers import NewSystemDriver, PureLLMDriver
    if name == "frozen_old":
        from .frozen_old_driver import FrozenOldDriver
        return FrozenOldDriver(settings=Settings.for_test(data_dir), fake_model=FakeModel(answer))
    if name not in {"new_system", "pure_llm"}: raise DatasetError("eval_cli_system_invalid")
    return (NewSystemDriver if name == "new_system" else PureLLMDriver)(
        settings=Settings.for_test(data_dir), fake_model=FakeModel(answer))


def _fixed_system_spec(name: str, answer: AnswerType) -> SystemSpec:
    if name == "frozen_old":
        from .frozen_old_driver import frozen_old_system_spec
        return frozen_old_system_spec(answer)
    if name not in {"new_system", "pure_llm"}:
        raise DatasetError("eval_cli_system_invalid")
    from app.prompts import HOST_SYSTEM_PROMPT
    root = Path(__file__).resolve().parents[1]
    sources = ("eval/run_cli.py", "eval/contracts.py", "eval/run_contracts.py", "eval/runner.py", "eval/drivers.py",
        "eval/metrics.py", "eval/catalog.py", "app/ai_host.py", "app/host_context.py", "app/host_rules.py",
        "app/host_evidence.py", "app/question_normalization.py", "app/model_gateway.py", "app/runtime.py",
        "app/testing.py", "app/rule_contract.py", "app/rag.py", "app/schemas.py", "app/host_cache.py",
        "app/audit_events.py", "app/audit_context.py", "app/baselines.py", "app/config.py", "app/paths.py",
        "app/model_admission.py", "app/rate_policy.py", "app/rate_limit.py", "app/request_guards.py",
        "app/request_lifecycle.py", "app/scoring.py", "app/prompts.py", "app/__init__.py", "eval/__init__.py",
        "eval/manifest.py", "eval/inventory.py", "eval/grouping.py", "eval/proofs.py", "eval/legacy.py", "eval/comparison.py")
    import hashlib
    fingerprints = {name: hashlib.sha256(_read_copy(checked_path(root / name))).hexdigest() for name in sources}
    return SystemSpec(name=name, implementationDigest=digest({"systemName": name, "sourceDigests": fingerprints}),
        promptDigest=digest({"systemPrompt": HOST_SYSTEM_PROMPT, "hostRenderer": fingerprints["app/ai_host.py"],
            "contextRenderer": fingerprints["app/host_context.py"], "protocol": "strict-five-json-v1",
            "renderDependencies": {source: fingerprints[source] for source in (
                "app/rag.py", "app/schemas.py", "app/host_evidence.py", "app/baselines.py", "app/prompts.py")}}),
        adapterId="injected-fake-v1", providerId="fake", modelId=f"fake-five-{ANSWERS.index(answer)}",
        engineVersion=HOST_ENGINE_VERSION, normalizationVersion="exact-v1", seed=0, executionEvidence="synthetic_fixture",
        budget=RunBudget(modelAttemptsPerCase=2, caseTimeoutSeconds=45.0, maxContextTurns=12, maxInputChars=8000,
            contextPolicyVersion="context-v1", usagePolicyVersion="provider-declared-v1"))


class SafeParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise DatasetError("eval_cli_arguments_invalid")


def _parser():
    parser = SafeParser(description="Private offline fake evaluation, not real model quality.")
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    for field in ("dataset", "output"): run.add_argument("--" + field, required=True)
    run.add_argument("--system", choices=("new_system", "pure_llm", "frozen_old"), required=True)
    run.add_argument("--repeat", type=int, choices=range(1, 11), required=True)
    run.add_argument("--fake-answer", choices=ANSWERS, required=True)
    compare = actions.add_parser("compare")
    compare.add_argument("--input", nargs="+", required=True)
    compare.add_argument("--output", required=True)
    return parser


def _paths(args):
    inputs = tuple(checked_path(Path(value)) for value in ([args.dataset] if args.action == "run" else args.input))
    output = checked_path(Path(args.output))
    if not 1 <= len(inputs) <= 30 or len(set(inputs)) != len(inputs): raise DatasetError("eval_cli_input_overlap")
    if output.exists() or output in inputs: raise DatasetError("dataset_output_exists")
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in inputs): raise DatasetError("dataset_output_overlap")
    return inputs, output


def _status(status, *, run_count=None, input_count=None, code=None, evidence=None):
    values = {"status": status}
    if code is not None: values["code"] = code
    if run_count is not None: values.update(runCount=run_count, inputCount=input_count, executionEvidence=evidence)
    print(json.dumps(values, ensure_ascii=False, allow_nan=False))


def main(argv=None):
    try:
        argv = sys.argv[1:] if argv is None else argv
        if type(argv) is not list or len(argv) > 128 or any(type(v) is not str or len(v) > 2048 for v in argv):
            raise DatasetError("eval_cli_arguments_invalid")
        args = _parser().parse_args(argv)
        paths, output = _paths(args)
        if args.action == "run":
            from .runner import EvaluationSetupCancelled, run_dataset
            snapshot = read_snapshot(paths[0])
            if snapshot.manifest.splitRole not in {"dev", "regression"}: raise DatasetError("eval_cli_holdout_forbidden")
            spec = _fixed_system_spec(args.system, args.fake_answer)
            reports = []
            stopped = False
            with TemporaryDirectory(prefix="turtle-soup-offline-eval-") as owned_dir:
                for index in range(args.repeat):
                    if stopped:
                        from .drivers import UnavailableDriver
                        driver = UnavailableDriver()
                    else:
                        try:
                            driver = _offline_driver(args.system, data_dir=Path(owned_dir), answer=args.fake_answer)
                        except KeyboardInterrupt:
                            stopped = True
                            from .drivers import UnavailableDriver
                            driver = UnavailableDriver()
                    try:
                        report = run_dataset(snapshot, system=spec, driver=driver, repeat_index=index, repeat_count=args.repeat)
                    except EvaluationSetupCancelled:
                        # Cancellation before the runner's first decision has
                        # no model dispatch; runner finally already closed it.
                        stopped = True
                        from .drivers import UnavailableDriver
                        report = run_dataset(snapshot, system=spec, driver=UnavailableDriver(),
                            repeat_index=index, repeat_count=args.repeat)
                    reports.append(report)
                    stopped |= not report.complete
            bundle = verify_run_bundle(RunBundle(reports=tuple(reports)))
            _write_new(bundle, output)
            complete = all(r.complete for r in bundle.reports)
            _status("ready" if complete else "incomplete", run_count=len(reports), input_count=snapshot.manifest.inputCount,
                evidence=spec.executionEvidence)
        else:
            from .comparison import compare_runs
            reports = []; read_bytes = 0
            for path in paths:
                read_bytes += path.stat().st_size
                if read_bytes > MAX_BYTES: raise DatasetError("eval_comparison_limit")
                reports.extend(read_run_bundle(path).reports)
                if len(reports) > 30: raise DatasetError("eval_comparison_input_invalid")
            result = compare_runs(tuple(reports))
            _write_new(result, output)
            complete = result.complete
            _status("ready" if complete else "incomplete", run_count=len(reports), input_count=reports[0].manifest.inputCount,
                evidence=reports[0].manifest.system.executionEvidence)
        return 0 if complete else 2
    except DatasetError as error:
        _status("refused", code=error.code)
        return 1
    except Exception:
        _status("refused", code="eval_cli_refused")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
