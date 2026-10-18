/** Closed private aggregates. No user identities, claims or model-quality score. */
export const metricKeys = ['sessionsCreated', 'successfulChargedTurns', 'httpAttempts', 'feedbackSubmitted',
  'tasksCreated', 'candidatesCreated', 'reviewApproved', 'reviewRejected', 'candidatePublicationEvents'] as const;
export type MetricsCounts = Record<(typeof metricKeys)[number], number>;
const observationKeys = ['observedRuns', 'passedRuns', 'failedRuns', 'incompleteRuns', 'pendingRuns',
  'pendingExpiredRuns', 'plannedCases', 'attemptedCases', 'passedCases', 'counterexampleCases',
  'errorCases', 'unsupportedCases', 'notAttemptedCases'] as const;
export type MetricsObservationCounts = Record<(typeof observationKeys)[number], number>;
export type MetricsObservation = { state: 'unknown'; failedRuns: null; observedRuns: null;
  reason: 'source_not_integrated' | 'schema_5_required' | 'source_unavailable' } | (MetricsObservationCounts & {
  state: 'observed' | 'partial'; sourceCoverageStart: number; historicalBackfill: false;
  windowStartsBeforeCoverage: boolean; excluded: Record<'test' | 'synthetic' | 'unknown', MetricsObservationCounts> });
const taskKeys = ['queued', 'running', 'awaiting_review', 'needs_human', 'failed', 'cancelled'] as const;
const candidateKeys = ['pending', 'approved', 'rejected', 'published'] as const;
export interface MetricsWindow { start: number; end: number }
export interface MetricsFilters { soupId: string | null; puzzleVersion: string | null; ruleVersion: string | null }
export interface MetricsQuery extends MetricsWindow, MetricsFilters { limit: number; cursor: string | null }
export interface MetricsSummary {
  counts: MetricsCounts; excluded: Record<'test' | 'synthetic' | 'legacy' | 'unknown', MetricsCounts>;
  unscopedReal: MetricsCounts; taskStates: Record<(typeof taskKeys)[number], number>;
  candidateStates: Record<(typeof candidateKeys)[number], number>;
  taskPublication: { numerator: number; denominator: number; ratio: number | null };
  postPublicationRegression: MetricsObservation;
}
export interface MetricsCoverage {
  auditStartedAt: number | null; agentStartedAt: number | null;
  historicalAttemptsBackfilled: false; historicalRunsBackfilled: false;
  windowStartsBeforeAudit: boolean | null; windowStartsBeforeAgent: boolean | null;
  processAudit: null | { complete: boolean; permanentGap: boolean; dropped: number; fallbackCount: number; memoryCount: number; activeIO: number };
  state: 'complete' | 'partial' | 'unknown';
}
export interface MetricsGroup extends MetricsFilters { day: string; counts: MetricsCounts }
export interface MetricsPage { schemaVersion: 2 | 3; consistency: 'fixed_window_live_snapshot'; query: MetricsQuery;
  summary: MetricsSummary; coverage: MetricsCoverage; groups: MetricsGroup[]; nextCursor: string | null }
export interface MetricsExport { schemaVersion: 2 | 3; window: MetricsWindow; filters: MetricsFilters;
  summary: MetricsSummary; coverage: MetricsCoverage; groups: MetricsGroup[]; complete: true; generatedAt: number }
export class MetricsContractError extends Error {
  constructor() { super('统计数据暂时无法核验，请重新查询；不能当作完整结果。'); this.name = 'MetricsContractError'; }
}
function invalid(): never { throw new MetricsContractError(); }
function record(input: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return invalid();
  const data = input as Record<string, unknown>;
  if (Object.keys(data).length !== keys.length || keys.some(key => !Object.hasOwn(data, key))) return invalid();
  return data;
}
function integer(input: unknown, maximum = Number.MAX_SAFE_INTEGER): number {
  if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < 0 || input > maximum) return invalid();
  return input;
}
function stamp(input: unknown): number {
  if (typeof input !== 'number' || !Number.isFinite(input) || input < 0 || input > 253402300799) return invalid();
  return input;
}
function boolean(input: unknown): boolean { return typeof input === 'boolean' ? input : invalid(); }
function nullableBool(input: unknown): boolean | null { return input === null ? null : boolean(input); }
function text(input: unknown, maximum: number): string {
  return typeof input === 'string' && input.trim() && Array.from(input).length <= maximum ? input : invalid();
}
function cursor(input: unknown): string | null {
  if (input === null) return null;
  const value = text(input, 2048);
  return /^[A-Za-z0-9_-]+$/.test(value) ? value : invalid();
}
function filters(data: Record<string, unknown>): MetricsFilters {
  const version = (input: unknown, kind: string) => input === null ? null :
    typeof input === 'string' && new RegExp('^' + kind + '1:[0-9a-f]{64}$').test(input) ? input : invalid();
  return { soupId: data.soupId === null ? null : text(data.soupId, 200),
    puzzleVersion: version(data.puzzleVersion, 'p'), ruleVersion: version(data.ruleVersion, 'r') };
}
function window(data: Record<string, unknown>): MetricsWindow {
  const start = stamp(data.start), end = stamp(data.end);
  if (end < start || end - start > 31 * 86400) return invalid();
  return { start, end };
}
function counters<K extends readonly string[]>(input: unknown, keys: K): Record<K[number], number> {
  const data = record(input, keys);
  return Object.fromEntries(keys.map(key => [key, integer(data[key])])) as Record<K[number], number>;
}
function sum(values: Record<string, number>): number {
  return integer(Object.values(values).reduce((a, b) => a + b, 0));
}
function observationCounts(input: unknown): MetricsObservationCounts {
  const c = counters(input, observationKeys);
  if (integer(c.passedRuns + c.failedRuns + c.incompleteRuns + c.pendingRuns) !== c.observedRuns
    || c.passedCases < c.passedRuns || c.counterexampleCases < c.failedRuns || c.counterexampleCases > 100 * c.failedRuns
    || c.pendingExpiredRuns > c.pendingRuns || c.plannedCases < c.observedRuns || c.plannedCases > c.observedRuns * 100
    || c.notAttemptedCases < c.pendingRuns || c.attemptedCases > (c.observedRuns - c.pendingRuns) * 100
    || integer(c.passedCases + c.counterexampleCases + c.errorCases + c.unsupportedCases) !== c.attemptedCases
    || integer(c.attemptedCases + c.notAttemptedCases) !== c.plannedCases) return invalid();
  return c;
}
function observation(input: unknown, version: 2 | 3, period: MetricsWindow): MetricsObservation {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return invalid();
  if ((input as Record<string, unknown>).state === 'unknown') {
    const data = record(input, ['state', 'failedRuns', 'observedRuns', 'reason']);
    const allowed = version === 2 ? ['source_not_integrated'] : ['schema_5_required', 'source_unavailable'];
    if (data.failedRuns !== null || data.observedRuns !== null || typeof data.reason !== 'string'
      || !allowed.includes(data.reason)) return invalid();
    return { state: 'unknown', failedRuns: null, observedRuns: null, reason: data.reason as Extract<MetricsObservation, { state: 'unknown' }>['reason'] };
  }
  if (version !== 3) return invalid();
  const data = record(input, [...observationKeys, 'state', 'sourceCoverageStart', 'historicalBackfill', 'windowStartsBeforeCoverage', 'excluded']);
  if (data.state !== 'observed' && data.state !== 'partial' || data.historicalBackfill !== false) return invalid();
  const sourceCoverageStart = stamp(data.sourceCoverageStart), before = boolean(data.windowStartsBeforeCoverage);
  if (before !== (period.start < sourceCoverageStart) || (data.state === 'partial') !== before) return invalid();
  const counts = observationCounts(Object.fromEntries(observationKeys.map(key => [key, data[key]])));
  const excluded = record(data.excluded, ['test', 'synthetic', 'unknown']);
  return { ...counts, state: data.state, sourceCoverageStart, historicalBackfill: false,
    windowStartsBeforeCoverage: before, excluded: { test: observationCounts(excluded.test),
      synthetic: observationCounts(excluded.synthetic), unknown: observationCounts(excluded.unknown) } };
}
function summary(input: unknown, version: 2 | 3, period: MetricsWindow): MetricsSummary {
  const data = record(input, ['counts', 'excluded', 'unscopedReal', 'taskStates', 'candidateStates', 'taskPublication', 'postPublicationRegression']);
  const counts = counters(data.counts, metricKeys), excluded = record(data.excluded, ['test', 'synthetic', 'legacy', 'unknown']);
  const taskStates = counters(data.taskStates, taskKeys), candidateStates = counters(data.candidateStates, candidateKeys);
  const publication = record(data.taskPublication, ['numerator', 'denominator', 'ratio']);
  const numerator = integer(publication.numerator), denominator = integer(publication.denominator);
  const ratio = publication.ratio;
  const regression = observation(data.postPublicationRegression, version, period);
  if (sum(taskStates) !== counts.tasksCreated || sum(candidateStates) !== counts.candidatesCreated
    || denominator !== counts.tasksCreated || numerator > denominator
    || ratio !== (denominator === 0 ? null : numerator / denominator)) return invalid();
  return { counts, excluded: { test: counters(excluded.test, metricKeys), synthetic: counters(excluded.synthetic, metricKeys),
    legacy: counters(excluded.legacy, metricKeys), unknown: counters(excluded.unknown, metricKeys) },
    unscopedReal: counters(data.unscopedReal, metricKeys), taskStates, candidateStates,
    taskPublication: { numerator, denominator, ratio: ratio as number | null },
    postPublicationRegression: regression };
}
function coverage(input: unknown): MetricsCoverage {
  const data = record(input, ['auditStartedAt', 'agentStartedAt', 'historicalAttemptsBackfilled', 'historicalRunsBackfilled',
    'windowStartsBeforeAudit', 'windowStartsBeforeAgent', 'processAudit', 'state']);
  if (data.historicalAttemptsBackfilled !== false || data.historicalRunsBackfilled !== false
    || typeof data.state !== 'string' || !['complete', 'partial', 'unknown'].includes(data.state)) return invalid();
  let processAudit: MetricsCoverage['processAudit'] = null;
  if (data.processAudit !== null) {
    const p = record(data.processAudit, ['complete', 'permanentGap', 'dropped', 'fallbackCount', 'memoryCount', 'activeIO']);
    processAudit = { complete: boolean(p.complete), permanentGap: boolean(p.permanentGap), dropped: integer(p.dropped),
      fallbackCount: integer(p.fallbackCount), memoryCount: integer(p.memoryCount), activeIO: integer(p.activeIO) };
    if (processAudit.complete && (processAudit.permanentGap || processAudit.dropped || processAudit.fallbackCount
      || processAudit.memoryCount || processAudit.activeIO)) return invalid();
  }
  const result: MetricsCoverage = { auditStartedAt: data.auditStartedAt === null ? null : stamp(data.auditStartedAt),
    agentStartedAt: data.agentStartedAt === null ? null : stamp(data.agentStartedAt), historicalAttemptsBackfilled: false,
    historicalRunsBackfilled: false, windowStartsBeforeAudit: nullableBool(data.windowStartsBeforeAudit),
    windowStartsBeforeAgent: nullableBool(data.windowStartsBeforeAgent), processAudit, state: data.state as MetricsCoverage['state'] };
  if (result.state === 'complete' && (result.auditStartedAt === null || result.agentStartedAt === null
    || result.windowStartsBeforeAudit !== false || result.windowStartsBeforeAgent !== false || !result.processAudit?.complete)) return invalid();
  return result;
}
function groups(input: unknown, scope: MetricsWindow & MetricsFilters, counts: MetricsCounts, complete: boolean): MetricsGroup[] {
  if (!Array.isArray(input) || input.length > 100) return invalid();
  const seen = new Set<string>(), totals = counters(Object.fromEntries(metricKeys.map(key => [key, 0])), metricKeys);
  const result = input.map(item => {
    const data = record(item, ['day', 'soupId', 'puzzleVersion', 'ruleVersion', 'counts']);
    const source = filters(data), day = text(data.day, 10), bucket = Date.parse(day + 'T00:00:00Z') / 1000;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(bucket) || bucket < 0
      || new Date(bucket * 1000).toISOString().slice(0, 10) !== day || bucket >= scope.end || bucket + 86400 <= scope.start) return invalid();
    for (const key of ['soupId', 'puzzleVersion', 'ruleVersion'] as const) {
      if (scope[key] !== null && scope[key] !== source[key]) return invalid();
    }
    const identity = JSON.stringify([day, source.soupId, source.puzzleVersion, source.ruleVersion]);
    if (seen.has(identity)) return invalid();
    seen.add(identity);
    const values = counters(data.counts, metricKeys);
    for (const key of metricKeys) { totals[key] = integer(totals[key] + values[key]); }
    return { day, ...source, counts: values };
  });
  if (metricKeys.some(key => complete ? totals[key] !== counts[key] : totals[key] > counts[key])) return invalid();
  return result;
}
export function readMetricsPage(input: unknown): MetricsPage {
  const data = record(input, ['schemaVersion', 'consistency', 'query', 'summary', 'coverage', 'groups', 'nextCursor']);
  if ((data.schemaVersion !== 2 && data.schemaVersion !== 3) || data.consistency !== 'fixed_window_live_snapshot') return invalid();
  const q = record(data.query, ['start', 'end', 'soupId', 'puzzleVersion', 'ruleVersion', 'limit', 'cursor']);
  const query = { ...window(q), ...filters(q), limit: integer(q.limit, 100), cursor: cursor(q.cursor) };
  if (query.limit < 1) return invalid();
  const totals = summary(data.summary, data.schemaVersion, query), items = groups(data.groups, query, totals.counts, false), nextCursor = cursor(data.nextCursor);
  if (items.length > query.limit || nextCursor !== null && !items.length) return invalid();
  return { schemaVersion: data.schemaVersion, consistency: 'fixed_window_live_snapshot', query, summary: totals,
    coverage: coverage(data.coverage), groups: items, nextCursor };
}
export function readMetricsExport(input: unknown): MetricsExport {
  const data = record(input, ['schemaVersion', 'window', 'filters', 'summary', 'coverage', 'groups', 'complete', 'generatedAt']);
  if ((data.schemaVersion !== 2 && data.schemaVersion !== 3) || data.complete !== true) return invalid();
  const period = window(record(data.window, ['start', 'end'])), source = filters(record(data.filters, ['soupId', 'puzzleVersion', 'ruleVersion']));
  const totals = summary(data.summary, data.schemaVersion, period);
  const output: MetricsExport = { schemaVersion: data.schemaVersion, window: period, filters: source, summary: totals,
    coverage: coverage(data.coverage), groups: groups(data.groups, { ...period, ...source }, totals.counts, true),
    complete: true, generatedAt: stamp(data.generatedAt) };
  if (new TextEncoder().encode(JSON.stringify(output)).byteLength > 512 * 1024) return invalid();
  return output;
}
