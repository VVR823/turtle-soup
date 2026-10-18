# TS-05 admission and request safety design

Architectural implementation of the approved global plan, not new feature scope. Original authority: D:/CODE/turtle-soup-audit/TurtleSoup_秋招升级实施计划_2026-10-06.md, TS-05, D4/D23, A18–A21 and C04/C06/C15. Human intent remains a zero-new-cost real-user autumn-recruitment project with smooth normal gameplay. The user explicitly delegates local design/implementation and forbids stage confirmation pauses; this overrides skill approval menus, not production/paid/public/private-data authority.

## Selected approach

Extend the existing ModelGateway Condition and owner set with online waiting tickets; only admitted work creates a model worker. This is preferable to a separate semaphore that might be released at the wrong timeout boundary. Keep model-attempt ownership and request waiting separate. Redis/external brokers or an independent executor would add cost/operations or redundant ownership and are not needed for the declared single API process.

Online FIFO waiting capacity is 32, wait deadline min(original model deadline, admission start + 10s); online model deadline remains 45s including retries. Full queue rejects immediately. At most two actual local owners, at most one Agent owner, including cancelled/timed-out/cleanup-failed owners until confirmed cleanup. Agent cannot enter while online tickets wait. Agent admission does not create a second unbounded queue: busy leaves its persisted task queued; TS-05 supplies a capacity-10 pending-agent primitive, TS-14 wires it to durable 003 tasks. Persistent Agent scheduling itself is not enabled here.

Rate limiting checks independent monotonic-clock windows keyed by normalized client identity, endpoint template and policy identity. All policies for a request are evaluated atomically, append only once when admitted, and return a ceil-rounded Retry-After. Entries expire and have a finite key cap; when active identities fill that cap, reject new keys rather than silently forgetting an active limit. Site token is not a user identity. Authentication decisions never come from player body fields.

Proxy headers are ignored by default. With configured trusted proxy CIDRs and a valid immediate peer, walk X-Forwarded-For right-to-left through trusted hops to the nearest nontrusted IP; malformed/too-long chains fall back to the peer, not arbitrary attacker text. Do not enable trust-all; deployment template overwrites headers with remote_addr at its actual trust boundary and binds backend to loopback. Actual production topology remains a later external verification gate.

Application body handling rejects Content-Length >32768 or actual accumulated bytes >32768 before route/DB/model side effects; chunks and observer forwarding stay bounded. A 413 carries safe detail/code/requestId and CORS behavior is retained. Schema question 500/feedback 2000 limits remain. Admin capabilities fail closed when missing, use independent constant-time token comparison, and cannot be granted by X-Site-Token. Future Trace/metrics/candidate APIs reuse the same guard, not premature stub endpoints.

## Boundaries and error behavior

No future migrations; no actual Agent worker, cloud calls, purchases, deployments, server config reads or private player-text reads. Gateway rejection/timeout returns safe system_error; the reserved game turn is persisted noncharged through TS-04. Retries use the original deadline and actual attempts share the same local owner. Cancellation/expiry/shutdown cannot make a worker slot available prematurely. Settings and owned launcher explicitly gate Agent enablement on a single configured API worker; unknown real launch topology is a release blocker, not automatically inferred from an environment claim.

Queue snapshots are aggregate counts only, without tokens/questions/session IDs. Deterministic branches need no model ticket. API threadpool is the existing framework's bounded pool; the queue adds no waiting model threads. Agent fairness is intentionally online-first, without a background latency SLA. Logs/audit and exact normalized answer caching remain TS-09/06.

## Validation and self-review

Tests cover minute/hour precision, independent endpoints/policies, atomic multiwindow accounting, concurrent admits/key-cap/expiry; spoofed/trusted/malformed proxy chains; size by declared length and fragmented actual bodies, exact 32768 boundary and no side effects; site/admin token separation; two blocked owners plus 32 waiters, the 33rd rejection, 10s/45s deadline, cancelled ticket removal, online FIFO and Agent priority/capacity, retained cleanup-failed owners and single-worker gate. Use guarded fake clocks/events/transports; default async sandbox is broken, not production behavior. Complete offline/hash gate and one independent stage review follow.

Self-review: all A18–A21 paths mapped, queue owns no business state, models cannot choose traffic_class or budget, actual provider/production topology not fabricated. UI recovery remains TS-08. Shared TS-04 source is frozen until its current independent review returns; only disjoint TS-05 docs/new tests may proceed meanwhile.
