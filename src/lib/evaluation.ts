/** Stored legacy bodies stay legacy. Coverage and plot never imply reconstruction. */
export interface EvaluationResult {
  completion: number;
  evaluation: string;
  keyPointsCovered: string[];
  keyPointsMissing: string[];
  bottom: string;
  unlockSoupId?: string | null;
  verifiedCoverage?: number | null;
  reconstructionScore?: null;
  scoreVersion?: 'coverage-v1' | null;
  plotProgress?: number | null;
  unknownTopics?: string[];
}

function percentage(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100;
}

export function normalizeEvaluationDisplay(input: unknown): {
  coverageValue: number | null;
  coverageLabel: '已确认事实覆盖' | '历史分数（旧口径）';
  reconstructionLabel: '尚未独立评估';
  plotValue: number | null;
} {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('无效的评估结果');
  const value = input as Record<string, unknown>;
  if (!percentage(value.completion) || value.reconstructionScore != null) throw new Error('无效的评估分数');
  if (value.scoreVersion == null) {
    if (value.verifiedCoverage != null || value.plotProgress != null) throw new Error('旧结果不能伪装成已核验评分');
    return { coverageValue: value.completion, coverageLabel: '历史分数（旧口径）',
      reconstructionLabel: '尚未独立评估', plotValue: null };
  }
  if (value.scoreVersion !== 'coverage-v1' || !percentage(value.verifiedCoverage)
      || value.completion !== value.verifiedCoverage
      || (value.plotProgress != null && !percentage(value.plotProgress))) throw new Error('评估版本或分数不一致');
  return { coverageValue: value.verifiedCoverage, coverageLabel: '已确认事实覆盖',
    reconstructionLabel: '尚未独立评估', plotValue: value.plotProgress as number | null ?? null };
}
