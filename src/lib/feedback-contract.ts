/** Strict private admin responses. A player's expectedAnswer remains a claim. */
export type FeedbackStatus = 'pending' | 'approved' | 'rejected';
export interface Feedback {
  id: string; ts: string; soupId: string; soupTitle: string | null; question: string; hostAnswer: string;
  expectedAnswer: string; reason: string | null; status: FeedbackStatus; reviewedAt: string | null;
  mergedAt: null; mergedAnswer: null; rowVersion: number; safeForModel: boolean;
  sourceState: 'unverified' | 'linked' | 'legacy'; turnId: string | null;
}
export interface FeedbackPage { feedbacks: Feedback[]; totalInRange: number; nextCursor: string | null }
export class FeedbackContractError extends Error {
  constructor() { super('反馈数据暂时无法核验，请刷新后重试'); this.name = 'FeedbackContractError'; }
}
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
function invalid(): never { throw new FeedbackContractError(); }
function record(input: unknown, allowed: readonly string[]): Record<string, unknown> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return invalid();
  const data = input as Record<string, unknown>;
  if (Object.keys(data).some(key => !allowed.includes(key))) return invalid();
  return data;
}
function text(input: unknown, maximum: number): string {
  if (typeof input !== 'string' || !input.trim() || Array.from(input).length > maximum) return invalid();
  return input;
}
function nullableText(input: unknown, maximum: number): string | null {
  if (input === null) return null;
  if (typeof input !== 'string' || Array.from(input).length > maximum) return invalid();
  return input;
}
function historicalClaim(input: unknown, maximum: number): string {
  if (typeof input !== 'string' || input.length === 0 || Array.from(input).length > maximum) return invalid();
  return input;
}
export function feedbackNeedsManualCorrection(value: Feedback): boolean {
  return [value.soupId, value.question, value.hostAnswer, value.expectedAnswer].some(field => !field.trim());
}
function integer(input: unknown): number {
  if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < 0) return invalid();
  return input;
}
function identity(input: unknown): string { const id = text(input, 36); return uuid.test(id) ? id : invalid(); }
function timestamp(input: unknown): string {
  const ts = text(input, 40), parsed = Date.parse(ts);
  if (!Number.isFinite(parsed) || parsed < 0 || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(ts)) return invalid();
  return ts;
}
export function decodeFeedback(input: unknown): Feedback {
  const data = record(input, ['id', 'ts', 'soupId', 'soupTitle', 'question', 'hostAnswer', 'expectedAnswer', 'reason',
    'status', 'reviewedAt', 'mergedAt', 'mergedAnswer', 'rowVersion', 'safeForModel', 'sourceState', 'turnId']);
  if (!['pending', 'approved', 'rejected'].includes(String(data.status)) || typeof data.status !== 'string'
    || !['unverified', 'linked', 'legacy'].includes(String(data.sourceState)) || typeof data.sourceState !== 'string'
    || typeof data.safeForModel !== 'boolean' || data.mergedAt !== null || data.mergedAnswer !== null) return invalid();
  return { id: identity(data.id), ts: timestamp(data.ts), soupId: historicalClaim(data.soupId, 200),
    soupTitle: nullableText(data.soupTitle, 500), question: historicalClaim(data.question, 500), hostAnswer: historicalClaim(data.hostAnswer, 100),
    expectedAnswer: historicalClaim(data.expectedAnswer, 100), reason: nullableText(data.reason, 2000), status: data.status as FeedbackStatus,
    reviewedAt: data.reviewedAt === null ? null : timestamp(data.reviewedAt), mergedAt: null, mergedAnswer: null,
    rowVersion: integer(data.rowVersion), safeForModel: data.safeForModel, sourceState: data.sourceState as Feedback['sourceState'],
    turnId: data.turnId == null ? null : identity(data.turnId) };
}
export function decodeFeedbackPage(input: unknown): FeedbackPage {
  const data = record(input, ['feedbacks', 'totalInRange', 'nextCursor']);
  if (!Array.isArray(data.feedbacks) || data.feedbacks.length > 100) return invalid();
  const feedbacks = data.feedbacks.map(decodeFeedback), totalInRange = integer(data.totalInRange);
  if (totalInRange < feedbacks.length || new Set(feedbacks.map(item => item.id)).size !== feedbacks.length) return invalid();
  const nextCursor = data.nextCursor === null ? null : text(data.nextCursor, 512);
  if (nextCursor !== null && !/^[A-Za-z0-9_-]+$/.test(nextCursor)) return invalid();
  return { feedbacks, totalInRange, nextCursor };
}
export function decodeFeedbackReview(input: unknown, id: string, previousVersion: number, status: 'approved' | 'rejected'): Feedback {
  const data = record(input, ['ok', 'feedback']);
  if (data.ok !== true) return invalid();
  const item = decodeFeedback(data.feedback);
  if (item.id !== identity(id) || item.rowVersion !== integer(previousVersion) + 1
    || item.status !== status || item.reviewedAt === null) return invalid();
  return item;
}
