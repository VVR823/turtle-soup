# TS17 verified container input implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline and test-driven-development. No new reviewer for this unit; the TS17 whole-stage reviewer remains pending.

**Goal:** Prepare a new, exact, code-only container input directory from a verified release, without reading the working repository's private trees.

**Architecture:** Reuse the backend/standalone release verifiers. Copy only their digest-listed (not authenticated or cryptographically signed) files and original receipt into `release/`. An independent consumer compares the new context against the still-verified original artifact. No Docker recipe/runtime is claimed verified without Docker.

**Spec:** ../specs/2026-10-12-ts17-local-release-design.md

## Global constraints and rulings

- Existing HEAD/index/player data and historical artifacts remain untouched. Targets are new direct children of the actual project `.cache`; reject root/ancestor junctions and overlaps.
- Zero installation, pulls, network, production, Git writes or provider calls. All tests use native owned synthetic files, including actual Windows junctions.
- Ruling: prove context selection now; hold Linux Dockerfile/build/runtime/image digest choices separately. Missing Docker is not permission to invent green image evidence. The old Dockerfiles remain retired/unsafe, not approved by this unit.
- Ruling: verifier requires the original verified artifact, rather than trusting a resealable context manifest alone. Changed or unavailable original means refusal, not an authenticated provenance claim.
- Continuous authorization overrides skill handoff pauses; no phase confirmation. Keep failed output for investigation, never automatically delete source/target.

## Review focus

Private canaries mixed into an artifact; redirected ancestors; re-sealed/extra context bytes; partially copied input after source mutation; existing output sentinel preservation. Each gets an actual filesystem test.

## Task 1: explicit verified context

Create `scripts/container-context-policy.mjs` and `scripts/tests/container-context-policy.test.mjs`; register test in existing harness command without changing lock/dependencies.

Interfaces: `buildContainerContext(kind, artifact, target)` and `verifyContainerContext(kind, artifact, target)` return canonical schema1 metadata `{localOnly:true, productionReady:false, containerBuildVerified:false, kind, sourceManifestDigest, files}`; kind exactly backend/frontend. All paths absolute. Consumes `verifyBackendRelease` or `verifyStandaloneRelease` and their actual receipt/files.

- [x] Write tests with dynamic import existence assertion, then native RED (not import exception). Actual 11 assertions failed because policy missing; fixture release builders remain real positive controls.
- [x] Implement exact artifact file/receipt copy under `release/`; reject unsafe target/ancestors before writing. Compare current verified source and copied bytes after copy; write canonical context manifest exclusively.
- [x] Verify actual byte differences, extra directory/file, receipt re-sealing, missing file, source corruption, invalid kind, overlap/existing targets, and real NTFS junctions refuse; unchanged valid backend/frontend pass. 11 native PASS plus 3 passing characterization cases for real source mutation/private canaries; not claimed as an additional RED cycle.
- [x] Whole harness46032 EXIT0/103PASS0SKIP/14.009s; subsequent whole offline35067 EXIT0: 2737Python (includes412Eval)+356frontend+103Node+3API=3199PASS/14existingSKIP, Python XML578.034s. Typecheck/lint separately EXIT0. Logs `.cache/ts17/container-context-{red,green,harness,offline,typecheck,lint}.log` and offline.xml retained. Pytest root-cache permission warning and Node inherited NO_COLOR/FORCE_COLOR warnings explicitly retained; no unsafe ACL/environment change just to hide them. Docker/runtime/Edge/whole-stage peer remain pending, not inferred from this gate.

No default Dockerfile is generated: this directory is a verified input, not permission to run the retired recipes against it or the repository. Actual container recipes and image evidence remain a separate explicit outstanding item.

Actual code-list backend context `.cache/ts17-container-input-141f4f34-1d2e-41a3-bdb5-8cea0a35e98d` has79files and manifest SHA3246f54e52870a99b79cc24ee26a4e213ac8fa32336ac020a1f36830f3157a26; its distinct source/artifact identities are in `.cache/ts17/container-context-measured.json`. Original239 WinPS5.1 digest d9662e98e3c431c02f996d57ed24139c5479ac2b3ada381df59d8444003b671a, HEAD c5765b68cb251a7c566e76e2887d335d6ed6b285 and index45C635EFDD2844F5A8DAC3CF3B6B7FBB4CAA6A54A2F247F3F8CC902C4CA275F5 all rechecked unchanged after the whole gate.
