'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { API_BASE, apiFetch, clearSiteToken, ApiAuthError, getUnlockedSoups } from '@/lib/api';
import {
  TurtleIcon, ArrowLeftIcon, CoffeeIcon,
} from '@/components/icons';

interface DifficultyLimits {
  xuermu: number;
  baozi: number;
  tianyi: number;
}

interface Soup {
  id: string;
  title: string;
  difficulty: number;
  difficultyLimits?: DifficultyLimits;
}

type Tone = 'danger' | 'accent' | 'success';

const TONE: Record<Tone, { text: string; pill: string; bar: string; num: string; dot: string }> = {
  danger: {
    text: 'text-danger',
    pill: 'bg-danger/10 text-danger border-danger/30',
    bar: 'from-danger/70 to-transparent',
    num: 'text-danger',
    dot: 'bg-danger',
  },
  accent: {
    text: 'text-accent-text',
    pill: 'bg-accent/10 text-accent-text border-accent/30',
    bar: 'from-accent-text/70 to-transparent',
    num: 'text-accent-text',
    dot: 'bg-accent',
  },
  success: {
    text: 'text-success',
    pill: 'bg-success/10 text-success border-success/30',
    bar: 'from-success/70 to-transparent',
    num: 'text-success',
    dot: 'bg-success',
  },
};

// 三个难度档（次数越少 = 难度越高）。颜色用语义令牌，不再用 emoji。
const LEVELS: Array<{
  key: keyof DifficultyLimits;
  name: string;
  tagline: string;
  desc: string;
  tone: Tone;
}> = [
  {
    key: 'xuermu',
    name: '许二木',
    tagline: '全能高手',
    desc: '提问次数最少，每一步都必须精准致命，只有真正的推理高手才能在极限中还原真相。',
    tone: 'danger',
  },
  {
    key: 'baozi',
    name: '包子',
    tagline: '偏科战神',
    desc: '中等提问次数，给你一定容错空间，但每一问仍需斟酌，偏科也能打出漂亮仗。',
    tone: 'accent',
  },
  {
    key: 'tianyi',
    name: '天一',
    tagline: '大师是好人吗',
    desc: '天一的想法总是天马行空，更多的提问次数越能激发他的潜能。',
    tone: 'success',
  },
];

export default function DifficultyPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const soupId = params.id || '';

  const [soup, setSoup] = useState<Soup | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!soupId) return;
    (async () => {
      try {
        const unlocked = getUnlockedSoups().join(',');
        const url = unlocked ? `/api/soups?unlocked=${encodeURIComponent(unlocked)}` : '/api/soups';
        const res = await apiFetch(url);
        const data = await res.json();
        const list: Soup[] = data.soups || [];
        const found = list.find(s => s.id === soupId) || null;
        setSoup(found);
      } catch (err) {
        if (err instanceof ApiAuthError) {
          clearSiteToken();
          window.location.reload();
          return;
        }
        setSoup(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [soupId]);

  return (
    <div className="min-h-screen bg-canvas text-fg">
      {/* 背景装饰 */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -top-40 -right-40 h-80 w-80 rounded-full bg-accent/10 blur-3xl" />
        <div className="absolute top-1/2 -left-20 h-60 w-60 rounded-full bg-surface-2/60 blur-3xl" />
      </div>

      {/* Header：左对齐不对称，与首页风格统一 */}
      <header className="relative border-b border-border/60">
        <div className="mx-auto max-w-4xl px-6 py-12">
          <button
            onClick={() => router.push('/')}
            className="btn btn-ghost mb-6 px-2 py-2"
            aria-label="返回大厅"
          >
            <ArrowLeftIcon className="h-4 w-4" />
            返回大厅
          </button>
          <div className="flex items-center gap-3">
            <TurtleIcon className="h-9 w-9 text-accent-text" />
            <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">
              选择难度
            </h1>
          </div>
          <p className="mt-3 max-w-xl text-fg-subtle">
            {soup ? (
              <>
                正在挑战：<span className="font-medium text-accent-text">{soup.title}</span> · 次数越少，难度越高
              </>
            ) : (
              '加载中…'
            )}
          </p>
        </div>
      </header>

      {/* 难度卡片 */}
      <main className="relative mx-auto max-w-4xl px-6 py-10">
        {loading && (
          <div className="flex items-center justify-center py-20 text-fg-subtle">
            <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent-text" />
            <span className="ml-3">加载中…</span>
          </div>
        )}

        {!loading && !soup && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border py-20 text-center">
            <p className="text-xl text-fg-muted">没有找到这道汤哦~</p>
            <button
              onClick={() => router.push('/')}
              className="btn btn-ghost mt-4"
            >
              <ArrowLeftIcon className="h-4 w-4" />
              返回大厅
            </button>
          </div>
        )}

        {!loading && soup && (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            {LEVELS.map((lv, i) => {
              const count = soup.difficultyLimits?.[lv.key];
              const hasLimit = typeof count === 'number';
              const tone = TONE[lv.tone];
              return (
                <div key={lv.key} className="animate-fade-up" style={{ animationDelay: `${i * 90}ms` }}>
                <button
                  onClick={() => router.push(`/game/${soup.id}?level=${lv.key}`)}
                  className="card group relative flex flex-col overflow-hidden p-6 text-left transition-all duration-300 hover:-translate-y-1.5 hover:border-accent-text/40 hover:shadow-2xl hover:shadow-black/40"
                >
                  {/* 顶部装饰条 */}
                  <div
                    className={`absolute left-0 right-0 top-0 h-1 bg-gradient-to-r ${tone.bar}`}
                    aria-hidden="true"
                  />

                  <div className="flex items-center justify-between">
                    <span
                      className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${tone.pill}`}
                    >
                      {lv.tagline}
                    </span>
                    <span className={`h-2.5 w-2.5 rounded-full ${tone.dot}`} aria-hidden="true" />
                  </div>

                  <h3 className={`mt-4 font-display text-2xl font-bold text-fg group-hover:text-accent-text transition-colors`}>
                    {lv.name}
                  </h3>

                  <p className="mt-2 flex-1 text-sm leading-relaxed text-fg-muted">
                    {lv.desc}
                  </p>

                  <div className="mt-5 flex items-end justify-between">
                    <div>
                      <div className={`text-3xl font-extrabold ${tone.num}`}>
                        {hasLimit ? count : '∞'}
                      </div>
                      <div className="mt-0.5 text-xs text-fg-subtle">次提问机会</div>
                    </div>
                    <span className={`btn btn-accent`}>
                      开始
                      <ArrowLeftIcon className="h-4 w-4 rotate-180 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </div>
                </button>
                </div>
              );
            })}
          </div>
        )}
      </main>

      <footer className="relative border-t border-border/60 py-8 text-center text-sm text-fg-subtle">
        许二木海龟汤自助 · 选好难度，开始你的推理
        <div className="mt-3">
          <button
            onClick={() => router.push('/')}
            className="btn btn-accent"
          >
            <CoffeeIcon className="h-4 w-4" />
            请作者喝杯奶茶
          </button>
        </div>
      </footer>
    </div>
  );
}
