// 海龟汤系统 TypeScript 类型定义

export interface Soup {
  id: string;
  title: string;
  surface: string;
  bottom: string;
  bottomSummary?: string; // 汤底精简摘要，用于 LLM 判断时替代完整汤底以省 token
  checkpoints: Checkpoint[];
  tags: string[];
  difficulty: number;
  source: string;
  difficultyLimits?: DifficultyLimits; // 三个难度档的提问次数上限（手动设置）
  confusionPoints?: ConfusionPoint[]; // 易错点：作者锁死最易踩坑的问法，LLM 遇到严格按给定答案回
}

/** 易错点：玩家易误解/易让主持人误判的提问，及其正确回答 */
export interface ConfusionPoint {
  q: string; // 玩家可能问的易错表述（展示用，便于作者回忆坑点）
  a: '是' | '不是' | '是也不是' | '算是' | '与此无关';
  match?: string[]; // 触发正则（任一命中即直接返回 a，确定性兜底，不依赖 LLM 服从）
  note?: string; // 可选说明，帮助 LLM 理解为何如此判（同时注入提示词当备份）
}

/** 难度档：许二木 / 包子 / 天一 */
export interface DifficultyLimits {
  xuermu: number; // 许二木档次数
  baozi: number;  // 包子档次数
  tianyi: number; // 天一档次数
}

export interface Checkpoint {
  key: string;
  answer: boolean | 'unknown';
  hint?: string;
  category?: string;
  aliases?: string[]; // 同义词/口语化表达，提升 RAG 命中率
}

export interface Message {
  role: 'user' | 'host';
  content: string;
  timestamp: number;
}

export interface GameSession {
  id: string;
  soupId: string;
  status: 'playing' | 'solved' | 'given_up';
  messages: Message[];
  questionsAsked: number;
  solvedAt?: number;
  givenUpAt?: number;
}
