# TS-05 independent read-only stage review

Repo D:/CODE/turtle-soup, branch codex/ts02-storage-foundation, HEAD/base c5765b68cb251a7c566e76e2887d335d6ed6b285. Implementation is intentional uncommitted work, so HEAD..HEAD is NOT its diff. Use git diff HEAD for tracked changes, plus read the untracked listed modules/tests. Preserve all earlier TS-01–04 and user edits. No commits/push/production/private-data reads/cloud calls/subagents.

## Requirements and review authority

- Spec: docs/superpowers/specs/2026-10-08-ts05-admission-design.md
- Plan: docs/superpowers/plans/2026-10-08-ts05-admission.md
- Rulings/evidence: docs/superpowers/plans/2026-10-08-ts05-progress.md
- Original plan/acceptance/tests: D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md, TurtleSoup_秋招升级验收清单_2026-10-06.md, TurtleSoup_升级测试计划_2026-10-06.md; TS-05 A18–A21/C04/C06/C15.

## Source scope

Read full backend/app/rate_policy.py, rate_limit.py, request_guards.py, model_admission.py, model_gateway.py, runtime.py, config.py, plus TS-05 integration in main.py and ai_host.py. Review scripts/run-backend.py, backend/.env.example and deploy/templates/turtle-soup-api.{conf,service}. TS-04 game_service/game_store/request_lifecycle may be read as dependencies; already-reviewed earlier-stage wholesale work is not a new TS-05 rewrite. No content reads from real dotenv/backend/data/root data.

Tests: test_rate_limit_windows.py (9), test_proxy_identity.py (10), test_rate_limit_dependencies.py (7), test_request_guards.py (17), test_launch_policy.py (8), test_model_admission.py (26): 77 TS-05 tests. Existing gateway/adapter/disconnect/typed host/settings/API/TS04 regressions are integration evidence.

## Fresh parent verification

- 126 admission/gateway/adapter/disconnect/typed-host tests passed (.cache/ts05/admission-green.xml).
- Post-launch full gate 466 passed / 9 skipped; latest post-admission gate 476 pytest + 7 Vitest + 6 harness + 3 API-only Playwright = 492 passed / 9 skipped, exit 0 (.cache/ts05/admission-full-gate.xml).
- 239 real runtime files unchanged, SHA256 d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a; owned test server PID 98600 exited normally. Typecheck and git diff --check exit 0. Existing cache ACL/CRLF warnings retained.
- Synthetic 100 arrivals: owners 2, waiting 32, workers 2, admitted 2/refused 66/cancelled 32. No throughput, cloud quality, real-user or deployed proxy evidence.

## Review Focus (verbatim)

1. A rejected hour window cannot partially consume another policy or lose retained activity when keys hit capacity; denied responses must have a usable Retry-After.
2. Chained/spoofed proxy headers and malformed peer addresses cannot select another identity or bypass independent administrator access.
3. Fragmented/deceptive-length bodies cannot exceed 32KiB or race ASGI disconnect/body observers into losing input or creating games after refusal.
4. A full queue plus two ignoring-cancel/cleanup-failed owners cannot create extra model workers, release early or hang shutdown/wait indefinitely.
5. A waiting/partially cancelled online ticket cannot allow new Agent work to overtake it; admission and model retry share one deadline/actual attempt budget and multi-worker mismatch cannot enable Agent.

## Adaptations and boundaries

One fresh reviewer, one subsequent Important/Critical TDD fix pass, no reviewer fanout or re-review. Use gstack review checklist/edge-case judgment and Superpowers code-reviewer.md; native dirty/local/no-remote adaptation, not PR shipping. Record declined-to-judge behaviors individually. Labels follow user effects, not merely spec silence. No production/topology/provider/OS/UI/human quality gate signed off. PendingAgentQueue is a runtime-owned in-memory intent primitive; durable 003 queue/worker/budget ledger integration remains required TS-14 work.

Readonly review may run guarded offline tests. New probes only in .cache/ts05/reviewer-probes, use repository conftest by --confcutdir/explicit pytest root and do not change production/tests/index/HEAD. Default Windows async sandbox is known to hang; obtain normal automatic approval for relevant offline async tests, never bypass rejection. If quota fails preserve findings and return a precise limit; no upgrade/paid model.
