# TS17 retained frontend minors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for approved inline execution. No per-unit reviewer; ONE TS17 whole-stage reviewer after all local units.

**Goal:** Close TS15 M1/M2 without granting new approval, publication, polling privileges or game-path work.
**Architecture:** Existing closed wire decoder gains two availability/report predicates. Existing token-owned active-run effect owns one timeout and one visibility listener; a timer consumed while hidden is rearmed on foreground, not on each visibility event and never during an in-flight poll.
**Tech Stack:** TypeScript, React, installed Vitest/Testing Library; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-12-ts17-local-release-design.md; exact findings docs/ts15-review-report.md M1/M2.

## Global Constraints

- LOCAL synthetic fixtures only, no provider/data/production/Git writes; original game flow unchanged.
- Existing authorization/rate/busy/terminal stops and request epoch fences remain authoritative.
- Whole-suite/Edge/ONE stage peer still required; selected evidence is not stage acceptance.

## Review Focus

- stale/unavailable carrying a prior review must be rejected, not rendered as fresh material (Task1).
- ready carrying coherently failed or incomplete report must be rejected (Task1).
- historical complete published material and minimal unavailable without review remain readable (Task1 controls).
- returning from hidden tick must resume a bounded GET only, no POST; repeated visibility must not duplicate requests (Task2).
- terminal/error/busy/token-unmount stops must survive visibility events; late pre-cancel response fence remains (Task2 controls).

### Task1: candidate availability/report binding

Files: modify `src/lib/agent-review-contract.ts`; test `src/lib/agent-review-contract.test.ts`.
Interfaces: existing `decodeCandidateDetail(value: unknown, expectedId: string): CandidateDetail`; preserve exact public shape/error class.

- [ ] Add parameterized stale/unavailable-with-review and ready failed/incomplete tests, coherent counts/cases so failure pins availability, not malformed report syntax.
- [ ] Run `npm run test:frontend -- src/lib/agent-review-contract.test.ts`, preserve genuine RED log.
- [ ] Reject review when availability stale/unavailable and report.status != complete only when ready; retain historical complete and minimal unavailable existing controls.
- [ ] Rerun file GREEN then frontend suite/typecheck/lint before unit closure.

### Task2: visible active-run observation recovery

Files: modify `src/components/AgentReviewPanel.tsx`; test `src/components/AgentReviewPanel.test.tsx`.
Interfaces: existing `loadStatus(run: string, initial=false)`/token epoch; effect dependencies `[status,pollStopped,busy]` unchanged. Listener only schedules GET, never mutates/cancels/reauthorizes automatically.

- [ ] Real mounted panel/fake-time test: running status; hide before3000ms; no GET at hidden tick; restore+visibility twice; exactly one GET within3000ms; unresolved GET blocks duplicate visibility polls; terminal reply prevents subsequent GET/POST.
- [ ] Native error503 case after foreground GET stops future timers and visibility; retain existing late-cancel and token ownership tests. Preserve genuine RED log.
- [ ] Effect-local `timer`, `inFlight`, `disposed`; schedule one3000ms timer only while visible/notdisposed/notinflight/noexistingtimer; remove listener+clear timer on cleanup. No global observer or hidden background calls.
- [ ] Same files GREEN, frontend whole suite/typecheck/lint; record current evidence without claiming whole TS17/real browser done.

Self-review: two existing findings only; actual field names/statuss/effect fence inspected. User autonomous approval overrides phase handoff/commit prompts. TS14 registry is already present at current source; investigate persisted audit controls separately, no speculative duplicate fix. TS16 translation/D25/D8/runbook remain separate next units.
