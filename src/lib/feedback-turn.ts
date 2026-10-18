import type { SessionSnapshot } from './game-contract';

export interface FeedbackTurn { soupId: string; soupTitle: string; turnId: string; question: string; hostAnswer: string }
/** Only an explicit unique completed public pair. Never infer from an adjacent legacy row. */
export function feedbackTurn(session: SessionSnapshot, index: number): FeedbackTurn | null {
  const host = session.messages[index];
  if (!host || host.role !== 'host' || host.isFreeReminder || typeof host.turnId !== 'string'
    || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(host.turnId)
    || !['是', '不是', '是也不是', '算是', '与此无关'].includes(host.content)) return null;
  const paired = session.messages.slice(0, index).filter(row => row.turnId === host.turnId && row.role === 'user');
  if (paired.length !== 1 || !paired[0].content.trim() || Array.from(paired[0].content).length > 500
    || session.messages.filter(row => row.turnId === host.turnId && row.role === 'host').length !== 1) return null;
  return { soupId: session.soupId, soupTitle: session.soupTitle, turnId: host.turnId,
    question: paired[0].content, hostAnswer: host.content };
}
