'use client';

import { useEffect, useRef, useState } from 'react';
import { getPlayedSoups } from '@/lib/api';
import { loadPublicCatalog, type PublicSoup } from '@/lib/catalog';
import {
  SearchIcon, GiftIcon, CloseIcon, ArrowRightIcon, ArrowLeftIcon, CoffeeIcon,
} from '@/components/icons';

type Soup = PublicSoup;

/** 难度星级 */
function DifficultyStars({ level }: { level: number }) {
  return (
    <div className="flex items-center gap-0.5" title={`难度 ${level}/5`} aria-label={`难度 ${level} 星，共 5 星`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={`text-xs ${i < level ? 'text-accent-text' : 'text-fg-subtle/60'}`}
          aria-hidden="true"
        >
          ★
        </span>
      ))}
    </div>
  );
}

/** 统一的标签配色（明亮文字，暗底对比度 ≥ 4.5:1） */
const TAG_STYLES: Record<string, string> = {
  推理: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  入门: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  悬疑: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  情感: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  经典: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  恐怖: 'bg-red-500/10 text-red-400 border-red-500/20',
  心理: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  科幻: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  长篇: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  现实: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  温情: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  短篇: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
  彩蛋: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  隐藏: 'bg-purple-500/10 text-purple-300 border-purple-500/20',
  日常: 'bg-lime-500/10 text-lime-400 border-lime-500/20',
  惊悚: 'bg-red-500/10 text-red-400 border-red-500/20',
  露营: 'bg-green-500/10 text-green-400 border-green-500/20',
  克苏鲁: 'bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20',
  幻觉: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  BT: 'bg-pink-500/10 text-pink-400 border-pink-500/20',
  老年: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  幻想: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  感人: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  邪术: 'bg-amber-700/10 text-amber-500 border-amber-700/20',
  邻居: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  暗黑: 'bg-gray-700/20 text-gray-300 border-gray-600/30',
  动物: 'bg-lime-600/10 text-lime-400 border-lime-600/20',
  烧脑: 'bg-cyan-600/10 text-cyan-400 border-cyan-600/20',
  梦境: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  历史: 'bg-amber-600/10 text-amber-400 border-amber-600/20',
  猎奇: 'bg-orange-600/10 text-orange-400 border-orange-600/20',
  时间旅行: 'bg-cyan-600/10 text-cyan-400 border-cyan-600/20',
  民俗: 'bg-teal-600/10 text-teal-400 border-teal-600/20',
  校园: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  医院: 'bg-rose-600/10 text-rose-400 border-rose-600/20',
  警察: 'bg-indigo-600/10 text-indigo-400 border-indigo-600/20',
  医生: 'bg-emerald-600/10 text-emerald-400 border-emerald-600/20',
  孩子: 'bg-pink-500/10 text-pink-400 border-pink-500/20',
  家庭: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  反转: 'bg-fuchsia-600/10 text-fuchsia-400 border-fuchsia-600/20',
  犯罪: 'bg-red-700/10 text-red-500 border-red-700/20',
};

/** 未列出的标签自动哈希分配彩色兜底，保证所有标签都有颜色且同名标签固定颜色 */
const DYNAMIC_PALETTE = [
  'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  'bg-sky-500/10 text-sky-400 border-sky-500/20',
  'bg-purple-500/10 text-purple-400 border-purple-500/20',
  'bg-rose-500/10 text-rose-400 border-rose-500/20',
  'bg-amber-500/10 text-amber-400 border-amber-500/20',
  'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  'bg-lime-500/10 text-lime-400 border-lime-500/20',
  'bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20',
  'bg-violet-500/10 text-violet-400 border-violet-500/20',
  'bg-teal-500/10 text-teal-400 border-teal-500/20',
  'bg-orange-500/10 text-orange-400 border-orange-500/20',
  'bg-pink-500/10 text-pink-400 border-pink-500/20',
  'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
];

const getTagStyle = (tag: string) => {
  if (TAG_STYLES[tag]) return TAG_STYLES[tag];
  const idx = Array.from(tag).reduce((sum, c) => sum + c.charCodeAt(0), 0) % DYNAMIC_PALETTE.length;
  return DYNAMIC_PALETTE[idx];
};

/** 汤品卡片 */
function SoupCard({ soup, index, played }: { soup: Soup; index: number; played: boolean }) {
  const isHidden = soup.hidden;
  const preview = soup.surface.slice(0, 50) + (soup.surface.length > 50 ? '…' : '');

  return (
    <div className="animate-fade-up" style={{ animationDelay: `${index * 70}ms` }}>
      <a
        href={`/difficulty/${soup.id}`}
        className={`card group relative flex flex-col overflow-hidden transition-all duration-300 hover:-translate-y-1 hover:border-accent-text/40 hover:shadow-2xl hover:shadow-black/40 ${
          isHidden ? 'border-accent-text/30 bg-gradient-to-br from-surface to-accent/5' : ''
        }`}
      >
      {/* 顶部装饰条：统一暖金渐变（原多色循环改为品牌一致） */}
      <div
        className="h-1 w-full bg-gradient-to-r from-accent-text/70 to-transparent"
        aria-hidden="true"
      />

      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <h3
            className={`font-display text-lg font-bold transition-colors ${
              isHidden ? 'text-accent-text' : 'text-fg group-hover:text-accent-text'
            }`}
          >
            {isHidden && <GiftIcon className="mr-1 inline-block h-4 w-4 align-[-2px] text-amber-300" />}
            {soup.title}
          </h3>
          {isHidden ? (
            <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
              隐藏彩蛋
            </span>
          ) : (
            <DifficultyStars level={soup.difficulty} />
          )}
        </div>

        <div className="mt-2 flex flex-wrap gap-1.5">
          {played && (
            <span className="rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-xs text-success">
              ✓ 已玩过
            </span>
          )}
          {soup.tags.map(tag => (
            <span
              key={tag}
              className={`rounded-full border px-2 py-0.5 text-xs ${getTagStyle(tag)}`}
            >
              {tag}
            </span>
          ))}
          {isHidden && (
            <span className={`rounded-full border px-2 py-0.5 text-xs ${getTagStyle('彩蛋')}`}>
              彩蛋
            </span>
          )}
        </div>

        <p className="mt-3 flex-1 text-sm leading-relaxed text-fg-muted">
          {preview}
        </p>

        <div className="mt-4 flex items-center justify-end">
          <span className="btn btn-accent">
            开始推理
            <ArrowRightIcon className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </div>
    </a>
    </div>
  );
}

/** 分页控制（上一页 / 下一页 + 直达页码输入） */
function Pagination({
  totalPages,
  currentPage,
  onPageChange,
}: {
  totalPages: number;
  currentPage: number;
  onPageChange: (p: number) => void;
}) {
  const [draft, setDraft] = useState<{ page: number; value: string } | null>(null);
  const input = draft?.page === currentPage ? draft.value : String(currentPage);

  const handleJump = () => {
    const p = parseInt(input, 10);
    if (!Number.isNaN(p)) onPageChange(Math.min(totalPages, Math.max(1, p)));
  };

  return (
    <div className="flex flex-col items-center gap-4">
      <nav className="flex w-full max-w-xs items-center justify-between gap-2 sm:max-w-none sm:justify-center sm:gap-4" aria-label="汤品列表分页">
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          className="btn btn-ghost px-3 py-2 disabled:opacity-40 sm:px-4"
          aria-label="上一页"
        >
          <ArrowLeftIcon className="h-4 w-4" />
          <span className="hidden sm:inline">上一页</span>
        </button>
        <span className="text-sm text-fg-subtle">
          第 <span className="font-medium text-fg">{currentPage}</span> / {totalPages} 页
        </span>
        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          className="btn btn-ghost px-3 py-2 disabled:opacity-40 sm:px-4"
          aria-label="下一页"
        >
          <span className="hidden sm:inline">下一页</span>
          <ArrowRightIcon className="h-4 w-4" />
        </button>
      </nav>

      <div className="flex w-full max-w-xs items-center gap-2 rounded-xl border border-border bg-canvas px-3 py-2 text-sm text-fg-subtle sm:w-auto sm:bg-transparent sm:px-0 sm:py-0 sm:rounded-none sm:border-0">
        <span className="whitespace-nowrap">跳至第</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={totalPages}
          value={input}
          onChange={(e) => setDraft({ page: currentPage, value: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleJump();
          }}
          placeholder="页码"
          className="min-w-0 flex-1 rounded-md border border-border bg-canvas px-2 py-1.5 text-center text-sm text-fg outline-none transition-colors focus:border-accent-text sm:w-16 sm:flex-none"
          aria-label="输入页码"
        />
        <span className="whitespace-nowrap">页</span>
        <button
          onClick={handleJump}
          className="btn btn-accent px-3 py-1.5 text-xs whitespace-nowrap"
          aria-label="跳转"
        >
          跳转
        </button>
      </div>
    </div>
  );
}

/** 每页显示的汤品数量 */
const PAGE_SIZE = 6;

/** 主页：汤品选择大厅 */
export default function Home() {
  const [soups, setSoups] = useState<Soup[]>([]);
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [showDonate, setShowDonate] = useState(false);
  const [played, setPlayed] = useState<Set<string>>(new Set());
  const donateCloseRef = useRef<HTMLButtonElement>(null);
  // 请求控制器：切换搜索词时取消上一个未完成的请求，避免旧结果覆盖新结果（竞态）
  const soupsAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setPage(1);
      fetchSoups(query);
    }, 250);
    return () => {
      clearTimeout(t);
      soupsAbortRef.current?.abort();
    };
  }, [query]);

  // 赞赏模态：Esc 关闭 + 打开聚焦关闭按钮
  useEffect(() => {
    if (!showDonate) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowDonate(false);
    };
    window.addEventListener('keydown', onKey);
    donateCloseRef.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [showDonate]);

  async function fetchSoups(q = '') {
    // 取消上一个未完成的请求，保证只有最新一次搜索的结果会渲染
    soupsAbortRef.current?.abort();
    const controller = new AbortController();
    soupsAbortRef.current = controller;
    setLoading(true);
    setCatalogError('');
    try {
      const list = await loadPublicCatalog({ query: q, signal: controller.signal });
      if (soupsAbortRef.current !== controller || controller.signal.aborted) return;
      setSoups(list); setPlayed(new Set(getPlayedSoups()));
    } catch (err) {
      if (soupsAbortRef.current !== controller || controller.signal.aborted) return;
      setCatalogError(err instanceof Error ? err.message : '列表加载失败，请重试');
    } finally {
      // 只有当前请求才允许关闭 loading（被取消的旧请求不应影响新请求的加载状态）
      if (soupsAbortRef.current === controller && !controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-canvas text-fg">
      {/* 背景装饰 */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -top-40 -right-40 h-80 w-80 rounded-full bg-accent/10 blur-3xl" />
        <div className="absolute top-1/2 -left-20 h-60 w-60 rounded-full bg-surface-2/60 blur-3xl" />
      </div>

      {/* Header：左对齐不对称布局，破除 AI 默认居中 Hero（DESIGN_VARIANCE 6） */}
      <header className="relative border-b border-border/60">
        <div className="mx-auto max-w-5xl px-6 py-14">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] text-accent-text/70">
            <span className="h-px w-8 bg-accent-text/40" aria-hidden="true" />
            AI 主持 · 悬疑推理
          </div>
          <h1 className="mt-4 font-display text-4xl font-bold leading-[1.1] tracking-tight sm:text-5xl">
            许二木海龟汤
            <span className="bg-gradient-to-r from-accent-text to-accent bg-clip-text text-transparent">
              自助
            </span>
          </h1>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-fg-muted">
            选一道谜题，向 AI 主持人提问，用「是」与「不是」推理出藏在背后的真相。
          </p>
        </div>
      </header>

      {/* 搜索栏 */}
      <div className="relative mx-auto -mt-6 max-w-2xl px-6">
        <div className="panel flex items-center gap-3 px-4 py-3 shadow-xl shadow-black/30">
          <SearchIcon className="h-5 w-5 shrink-0 text-fg-subtle" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索海龟汤：标题 / 标签 / 汤面关键词…"
            aria-label="搜索海龟汤"
            className="w-full bg-transparent text-sm text-fg placeholder-fg-subtle outline-none"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="btn btn-ghost shrink-0 px-2 py-1 text-xs"
              aria-label="清除搜索"
            >
              清除
            </button>
          )}
        </div>
      </div>

      {/* 主内容 */}
      <main className="relative mx-auto max-w-5xl px-6 py-10">
        {catalogError && <div className="panel p-5"><p role="alert">{catalogError}</p>
          <button className="btn btn-ghost mt-3" onClick={() => void fetchSoups(query)}>重试列表</button></div>}
        {loading && (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="card animate-pulse overflow-hidden">
                <div className="h-1 w-full bg-border" />
                <div className="space-y-3 p-5">
                  <div className="flex items-start justify-between">
                    <div className="h-5 w-24 rounded bg-surface-2" />
                    <div className="h-4 w-12 rounded-full bg-surface-2" />
                  </div>
                  <div className="flex gap-1.5">
                    <div className="h-4 w-12 rounded-full bg-surface-2" />
                    <div className="h-4 w-12 rounded-full bg-surface-2" />
                    <div className="h-4 w-12 rounded-full bg-surface-2" />
                  </div>
                  <div className="h-3 w-full rounded bg-surface-2" />
                  <div className="h-3 w-2/3 rounded bg-surface-2" />
                  <div className="flex justify-end pt-2">
                    <div className="h-9 w-24 rounded-xl bg-surface-2" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && !catalogError && soups.length === 0 && !query && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border py-20 text-center">
            <p className="text-xl text-fg-muted">暂时没有海龟汤哦~</p>
            <p className="mt-1 text-sm text-fg-subtle">等待管理员添加新题</p>
          </div>
        )}

        {!loading && !catalogError && soups.length === 0 && query && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border py-20 text-center">
            <p className="text-xl text-fg-muted">
              没有找到与「{query}」相关的海龟汤
            </p>
            <p className="mt-1 text-sm text-fg-subtle">换个关键词试试吧</p>
          </div>
        )}

        {!loading && !catalogError && soups.length > 0 && (
          <>
            {query && (
              <p className="mb-4 text-sm text-fg-subtle">
                找到 {soups.length} 道与「{query}」相关的海龟汤
              </p>
            )}
            {(() => {
              const totalPages = Math.max(1, Math.ceil(soups.length / PAGE_SIZE));
              const currentPage = Math.min(page, totalPages);
              const pageSoups = soups.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
              const goPage = (p: number) => {
                setPage(Math.min(totalPages, Math.max(1, p)));
                window.scrollTo({ top: 0, behavior: 'smooth' });
              };
              return (
                <>
                  <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
                    {pageSoups.map((soup, i) => (
                      <SoupCard key={soup.id} soup={soup} index={i} played={played.has(soup.id)} />
                    ))}
                  </div>
                  {totalPages > 1 && (
                    <div className="mt-10">
                      <Pagination
                        totalPages={totalPages}
                        currentPage={currentPage}
                        onPageChange={goPage}
                      />
                    </div>
                  )}
                </>
              );
            })()}
          </>
        )}
      </main>

      {/* Footer */}
      <footer className="relative border-t border-border/60 py-8 text-center text-sm text-fg-subtle">
        许二木海龟汤自助 · AI 主持的海龟汤推理游戏
        <p className="mt-2 text-xs text-fg-subtle/70">
          答题规则经人工审核后发布；提问暂时失败时，请稍后重试~
        </p>
        <div className="mt-3">
          <button
            onClick={() => setShowDonate(true)}
            className="btn btn-accent"
          >
            <CoffeeIcon className="h-4 w-4" />
            请作者喝杯奶茶
          </button>
        </div>
      </footer>

      {/* 赞赏码模态框 */}
      {showDonate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-6 backdrop-blur-sm"
          onClick={() => setShowDonate(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="donate-title"
        >
          <div
            className="card w-[320px] max-w-[92vw] p-6 text-center shadow-2xl shadow-black/50"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <h3 id="donate-title" className="text-lg font-bold text-accent-text">
                  请作者喝杯奶茶
                </h3>
                <p className="mt-1 text-xs text-fg-subtle">
                  你的支持是我持续收录好汤的动力~
                </p>
              </div>
              <button
                ref={donateCloseRef}
                onClick={() => setShowDonate(false)}
                className="btn btn-ghost -mr-2 -mt-2 px-2 py-2"
                aria-label="关闭赞赏框"
              >
                <CloseIcon className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-4 flex items-center justify-center rounded-xl border border-border bg-canvas p-4">
              {/* 替换为你的微信赞赏码：把图片放到 public/donate.png，再把下面 src 改成 /donate.png */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/donate.jpg"
                alt="微信赞赏码"
                className="h-44 w-44 object-contain"
              />
            </div>
            <p className="mt-3 text-[11px] text-fg-subtle">微信扫一扫 · 自愿打赏</p>
            <button
              onClick={() => setShowDonate(false)}
              className="btn btn-accent mt-4 w-full"
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
