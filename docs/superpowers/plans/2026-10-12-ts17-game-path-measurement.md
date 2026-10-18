# TS17 D25 rule-hit/miss and log-growth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, approved inline/TDD; same ONE TS17 whole-stage reviewer.

**Goal:** Measure actual normal game HTTP rule-hit and model-fallback paths, all samples, synthetic audit/trace disk growth and actual lifespan cleanup without paid providers or private data.
**Architecture:** One explicitly synthetic Soup/FakeModel/TestClient/temporary data directory; fresh session per turn, create outside measured ask. Warm3+measure20 each of rule-hit and ordinary contextual miss; record actual typed audit/trace source plus model-call delta, so a reminder/error/cache disguise cannot become a successful sample. No product changes.
**Tech Stack:** Python/SQLite/FastAPI TestClient/FakeModel/pytest installed; no new dependencies or network.
**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md D25 and original D25.

## Global Constraints

- ONLY Settings.for_test(new temporarydir), explicit ownSoup/model; no dotenv/original catalog/user files.
- API measured scope includes turn persistence/audit/trace and in-process TestClient, not TCP/browser/provider SLA.
- warmups default3[0,10],samples default20[1,100]; bool/noninteger/outside rejected.
- Preserve every measured raw sample/error; failure has fixedcode/no success quantiles; owned temp/lifespan must close.
- Before-upgrade comparable report/real provider/RSS unknownnull; existing TS16 scale report not redone.

## Review Focus

- Rule-hit must actualsource deterministic/calls0/charged answer, not fake/no-op timing.
- Rule-miss must actualsource llm/calls1 every new session; warmups don't enable model reply caching.
- Native persisted sessions/turns/messages/charged/audit/trace counts must match complete workload.
- Failed answer/trace/audit observation never fabricates quantiles or silently drops a case.
- Actual Runtime/model/audit/ownedtmp cleanup must survive forced measurement failure.

### Task1: actual HTTP paths and bounded accounting

Files: create `backend/app/scripts/benchmark_game_paths.py`; create `backend/tests/test_game_path_benchmark.py`.
Interfaces: `measure_game_paths(*, warmups=3, samples=20)->dict`; CLI noargsprintsJSON/exits0 only complete. Reuse `nearest_rank` from benchmark_metrics; create_app, runtime_context, AuditEvent, FakeModel current interfaces; original validators/game flow unchanged.

- [ ] Write real default3/20 test: two sample arrays20 finite>=0; deterministic hit modelcalls0; llm miss modelcalls1; complete workload46sessions/46turns/92messages/46charged/184audits (46session_created/46turn_committed/92http_attempt)/46trace lines andfiles; serialized auditbytes/trace growth>0; actual resources cleanuptrue; conditional raw nearest-rank.
- [ ] Bounded overrides test0/1 actual2sessions/2turns/4messages/8audits; invalidbool/type/limits rejection cases before app construction.
- [ ] Forced fixture-only record failure through benchmark sample seam: failed fixedcode/no timingquantiles/actual runtimeclose/modelactive0/auditresidual0/tempremoved; no rawcanary; no business function monkeypatch.
- [ ] CLI noargsactualreport+exit, argumentrefusalnoexternalpath/stdout. Preserve genuineRED `node scripts/test-backend.mjs backend/tests/test_game_path_benchmark.py --junitxml=.cache/ts17/game-path-red.xml -o cache_dir=.cache/ts17/pytest-game-path`.
- [ ] Implement literal Chinese synthetic checkpoint rule-hitquestion `小明是凶手吗？` and ordinary contextualmiss `他是凶手吗？`; accept only actualkindanswer/isFreeReminderfalse/statecompleted/sessionquestions1 and trace/audit same turn/source/chargeable/source+modeldelta. Time only POSTask, observer checks outside.
- [ ] Record counts/byte growth beforeafter workload/finalDB-WAL sizes/CPU/Pythonallocation notRSS; nativeactualshutdown and tempdeletion. Selectedregressions+standaloneactualJSON; whole-project/Edge still finalstagegate.

Self-review: current public chatprojection does not expose source; private owned trace and turn_committed typed audit do, not inferred from replytext. Only synthetictrace enabled for this fixture; production default remains unchanged. Matching pre-upgrade evidence absent, reportunknown not pretend improvement. User autonomy overrides commit/handoff; no per-unit reviewer.
