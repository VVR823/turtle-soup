'use client';

import { useEffect, useRef, useState } from 'react';
import { metricKeys, MetricsContractError, readMetricsExport, readMetricsPage, type MetricsObservation, type MetricsPage, type MetricsQuery } from '@/lib/metrics-contract';

const labels = { sessionsCreated: '新建会话', successfulChargedTurns: '成功计次轮次', httpAttempts: 'HTTP尝试',
  feedbackSubmitted: '反馈提交', tasksCreated: '新建任务', candidatesCreated: '新建候选', reviewApproved: '审核批准',
  reviewRejected: '审核拒绝', candidatePublicationEvents: '候选发布事件' };
const API_BASE = process.env.NEXT_PUBLIC_API_BASE !== undefined ? process.env.NEXT_PUBLIC_API_BASE : 'http://localhost:8000';
const emptyFields = { start: '', end: '', soupId: '', puzzleVersion: '', ruleVersion: '', limit: '50' };
type Fields = typeof emptyFields;
function scope(query: MetricsQuery): URLSearchParams {
  const params = new URLSearchParams({ start: String(query.start), end: String(query.end) });
  for (const key of ['soupId', 'puzzleVersion', 'ruleVersion'] as const) if (query[key] !== null) params.set(key, query[key]);
  return params;
}
function requested(fields: Fields): URLSearchParams {
  const params = new URLSearchParams({ limit: fields.limit });
  for (const key of ['start', 'end'] as const) {
    if (fields[key]) {
      const timestamp = Date.parse(fields[key] + 'Z') / 1000;
      if (!Number.isFinite(timestamp)) throw new MetricsContractError();
      params.set(key, String(timestamp));
    }
  }
  for (const key of ['soupId', 'puzzleVersion', 'ruleVersion'] as const) if (fields[key].trim()) params.set(key, fields[key].trim());
  return params;
}
function verifyBinding(page: MetricsPage, params: URLSearchParams) {
  for (const [key, value] of params) {
    const actual = page.query[key as keyof MetricsQuery];
    if (actual !== (['start', 'end', 'limit'].includes(key) ? Number(value) : value)) throw new MetricsContractError();
  }
}
function failure(response: Response): string {
  if (response.status === 401) return '管理口令错误或已失效，请重新输入。';
  if (response.status === 429) {
    const retry = response.headers.get('Retry-After');
    return '请求较频繁，请稍后重试。' + (retry && /^\d{1,6}$/.test(retry) ? `建议等待${retry}秒。` : '');
  }
  if (response.status === 409) return '完整导出超过上限，请缩小时间、题目或版本范围。';
  if (response.status === 503) return '统计暂时不可用或繁忙；旧库需管理员显式完成004迁移，请稍后重试。';
  if (response.status === 422) return '查询格式或范围不符合要求：时间最多31天，题目和版本须有效。';
  return '统计请求失败，请稍后重试。';
}

function ObservationSummary({ value }: { value: MetricsObservation }) {
  if (value.state === 'unknown') return <p>发布后回归失败：未知；{value.reason === 'schema_5_required'
    ? '尚未启用005观测账本' : value.reason === 'source_unavailable' ? '来源暂时无法核验' : '可信来源未接入'}，不能当作0，也不能用发布前的候选测试代替。</p>;
  return <div className="space-y-1 text-sm">
    <p>先发布，再复查：按复查开始时间计入区间，规则筛选使用实际发布目标版本；回滚不抹掉历史复查。</p>
    <p>{value.observedRuns === 0 ? '真实发布后复查：0次；尚无真实观测，不代表零错误或质量达标。'
      : `真实发布后复查：${value.observedRuns}次；通过${value.passedRuns}次；反例${value.failedRuns}次；不完整${value.incompleteRuns}次；待完成${value.pendingRuns}次（其中已过期${value.pendingExpiredRuns}次）。`}</p>
    <p>真实复查计划共{value.plannedCases}例，已尝试{value.attemptedCases}例：通过{value.passedCases}例、反例{value.counterexampleCases}例、执行异常{value.errorCases}例、未支持{value.unsupportedCases}例；未尝试{value.notAttemptedCases}例。</p>
    <p>发现反例是答错；执行异常、未支持或没检查完是另一回事，不是正确答案，也不是语义准确率。</p>
    <p className="break-words">观测覆盖从{new Date(value.sourceCoverageStart * 1000).toISOString()}开始；{value.state === 'partial'
      ? '区间含启用前缺口，不能当作完整历史' : '区间在观测启用后'}；没有历史回填。</p>
    {Object.entries(value.excluded).map(([traffic, counts]) => <p key={traffic}>
      {{ test: '测试', synthetic: '合成', unknown: '来源不明' }[traffic as keyof typeof value.excluded]}复查：{counts.observedRuns}次；反例{counts.failedRuns}次；不完整{counts.incompleteRuns}次；待完成{counts.pendingRuns}次（其中已过期{counts.pendingExpiredRuns}次）；计划{counts.plannedCases}例，已尝试{counts.attemptedCases}例，未尝试{counts.notAttemptedCases}例；不计入真实流量。
    </p>)}
  </div>;
}

export default function MetricsPanel({ adminToken }: { adminToken: string }) {
  // A token change unmounts all private state. Returning to the same earlier
  // token is still a fresh mount, not permission to resurrect its old page.
  return <MetricsPanelState key={adminToken} adminToken={adminToken} />;
}

function MetricsPanelState({ adminToken }: { adminToken: string }) {
  const [fields, setFields] = useState<Fields>(emptyFields);
  const binding = JSON.stringify([adminToken, fields]);
  const epoch = useRef(0), active = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [loaded, setLoaded] = useState<{ binding: string; page: MetricsPage } | null>(null);
  const [operation, setOperation] = useState<{ binding: string; mode: string } | null>(null);
  const [notice, setNotice] = useState<{ binding: string; message: string; error: boolean } | null>(null);
  const page = loaded?.binding === binding ? loaded.page : null;
  const busy = operation?.binding === binding;
  useEffect(() => () => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    active.current?.abort(); active.current = null; epoch.current++;
  }, [adminToken]);

  function change(key: keyof Fields, value: string) {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    active.current?.abort(); active.current = null; epoch.current++;
    setOperation(null); setNotice(null); setLoaded(null);
    setFields(previous => ({ ...previous, [key]: value }));
  }
  async function run(mode: 'query' | 'next' | 'export') {
    if (!adminToken || active.current || mode !== 'query' && !page) return;
    const controller = new AbortController(), generation = ++epoch.current, bound = binding;
    active.current = controller; setOperation({ binding: bound, mode }); setNotice(null);
    if (mode === 'query') setLoaded(null);
    const current = () => active.current === controller && !controller.signal.aborted
      && epoch.current === generation;
    // Includes fetch and body decoding. Release ownership even if transport
    // ignores abort; epoch fencing prevents a late result or download.
    const timeout = setTimeout(() => {
      if (!current()) return;
      active.current = null; timer.current = null; epoch.current++;
      controller.abort(); setOperation(null);
      setNotice({ binding: bound, message: '统计请求超时，请重试或缩小查询范围。', error: true });
    }, 10000);
    timer.current = timeout;
    try {
      const params = mode === 'query' ? requested(fields) : scope(page!.query);
      if (mode === 'next') {
        if (!page!.nextCursor) return;
        params.set('limit', String(page!.query.limit)); params.set('cursor', page!.nextCursor);
      }
      const response = await fetch(`${API_BASE}/api/metrics/admin${mode === 'export' ? '/export' : ''}?${params}`, {
        headers: { 'X-Admin-Token': adminToken }, signal: controller.signal, cache: 'no-store',
      });
      if (!current()) return;
      if (!response.ok) {
        if (response.status === 401) setLoaded(null);
        setNotice({ binding: bound, message: failure(response), error: true }); return;
      }
      const raw: unknown = await response.json();
      if (!current()) return;
      if (mode === 'export') {
        const exported = readMetricsExport(raw);
        const expected = scope(page!.query);
        const actual = new URLSearchParams({ start: String(exported.window.start), end: String(exported.window.end) });
        for (const key of ['soupId', 'puzzleVersion', 'ruleVersion'] as const) if (exported.filters[key] !== null) actual.set(key, exported.filters[key]);
        if (actual.toString() !== expected.toString()) throw new MetricsContractError();
        if (!current()) return;
        const url = URL.createObjectURL(new Blob([JSON.stringify(exported)], { type: 'application/json' }));
        const link = document.createElement('a'); link.href = url; link.download = 'turtle-soup-metrics.json';
        try { document.body.append(link); link.click(); }
        finally { link.remove(); URL.revokeObjectURL(url); }
        setNotice({ binding: bound, message: '已下载完整统计；下载使用新快照，实时变化可能使计数与页面不同。', error: false });
      } else {
        const result = readMetricsPage(raw); verifyBinding(result, params);
        setLoaded({ binding: bound, page: result });
      }
    } catch (error) {
      if (current()) setNotice({ binding: bound, message: error instanceof MetricsContractError ? error.message : '网络或下载失败，请重新查询后重试。', error: true });
    } finally {
      clearTimeout(timeout);
      if (timer.current === timeout) timer.current = null;
      if (current()) { active.current = null; setOperation(null); }
    }
  }
  const message = notice?.binding === binding ? notice : null;
  return <section className="mt-6 rounded-xl border border-slate-200 bg-white p-4 text-slate-800" aria-labelledby="metrics-heading">
    <h2 id="metrics-heading" className="text-lg font-semibold">运行统计（私有）</h2>
    <p className="mt-2 text-sm">只手动查询，不自动轮询。默认最近7天，最多31天；区间含开始、不含结束，按UTC日期分组。</p>
    <p className="text-sm">只计明确的真实流量；测试、合成、旧数据和来源不明的记录单独列出，不是去重人数或模型正确率。</p>
    <div className="my-4 grid gap-3 sm:grid-cols-2">
      {(['start', 'end'] as const).map(key => <label key={key} className="text-sm">{key === 'start' ? '开始时间（UTC）' : '结束时间（UTC）'}
        <input aria-label={key === 'start' ? '开始时间（UTC）' : '结束时间（UTC）'} type="datetime-local" step="1" value={fields[key]}
          onChange={event => change(key, event.target.value)} className="mt-1 block w-full rounded border p-2" /></label>)}
      {(['soupId', 'puzzleVersion', 'ruleVersion'] as const).map(key => <label key={key} className="text-sm">
        {{ soupId: '题目ID', puzzleVersion: '来源题目版本', ruleVersion: '规则版本（业务来源／复查发布目标）' }[key]}
        <input aria-label={{ soupId: '题目ID', puzzleVersion: '来源题目版本', ruleVersion: '规则版本（业务来源／复查发布目标）' }[key]}
          value={fields[key]} maxLength={key === 'soupId' ? 200 : 67} onChange={event => change(key, event.target.value)} className="mt-1 block w-full rounded border p-2" /></label>)}
      <label className="text-sm">每页分组数<select aria-label="每页分组数" value={fields.limit} onChange={event => change('limit', event.target.value)} className="mt-1 block rounded border p-2"><option>50</option><option>100</option></select></label>
    </div>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={!adminToken || busy} onClick={() => void run('query')} className="rounded bg-slate-800 px-3 py-2 text-white disabled:opacity-50">查询统计</button>
      <button type="button" disabled={!page?.nextCursor || busy} onClick={() => void run('next')} className="rounded border px-3 py-2 disabled:opacity-50">下一页统计</button>
      <button type="button" disabled={!page || busy} onClick={() => void run('export')} className="rounded border px-3 py-2 disabled:opacity-50">下载完整统计</button>
    </div>
    {busy && <p role="status" className="mt-3">正在处理统计，请稍候…</p>}
    {message && <p role={message.error ? 'alert' : 'status'} className="mt-3">{message.message}</p>}
    {page && <div className="mt-4 space-y-3">
      <p className="break-words text-sm">实际区间（UTC）：{new Date(page.query.start * 1000).toISOString()} 至 {new Date(page.query.end * 1000).toISOString()}；当前窗口内创建队列的当前状态，不是截至结束时间的历史状态。</p>
      <p className="text-sm">分页固定区间，但不同请求是实时新快照；完整下载最多100组/512KiB，超限会拒绝，不给半份。</p>
      <div className="grid gap-1 sm:grid-cols-3">{metricKeys.map(key => <p key={key}>{labels[key]}：{page.summary.counts[key]}</p>)}</div>
      <ObservationSummary value={page.summary.postPublicationRegression} />
      <p>{page.summary.taskPublication.denominator === 0 ? '尚无任务（分母为0），不显示成功率。' : `任务发布比例：${page.summary.taskPublication.numerator}/${page.summary.taskPublication.denominator}（${(page.summary.taskPublication.ratio! * 100).toFixed(1)}%）；这不是修复正确率。`}</p>
      <p>任务状态：{Object.entries(page.summary.taskStates).map(([key, count]) => `${key}=${count}`).join('；')}。</p>
      <p>候选状态：{Object.entries(page.summary.candidateStates).map(([key, count]) => `${key}=${count}`).join('；')}。</p>
      <p className="text-sm">以下覆盖状态描述业务日志；发布后复查覆盖独立列示，不证明模型回答正确。</p>
      <p role="status">{page.coverage.state === 'unknown' ? '覆盖情况未知，已知记录仍保留；不能把缺失当作0。' : page.coverage.state === 'partial' ? '存在历史或待落盘审计缺口，已知记录仍保留；不能当作完整历史。' : '此刻已接入事件的审计覆盖完整，不证明模型回答正确。'}</p>
      {page.coverage.processAudit && <p className="text-sm">进程审计：待落盘{page.coverage.processAudit.fallbackCount + page.coverage.processAudit.memoryCount}，活动写入{page.coverage.processAudit.activeIO}，全进程丢失{page.coverage.processAudit.dropped}（不是本窗口精确丢失数）；永久缺口{page.coverage.processAudit.permanentGap ? '有' : '无'}。</p>}
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="text-left font-medium">排除流量与筛选前未完整绑定来源</caption><thead><tr><th>类别</th>{metricKeys.map(key => <th key={key} className="px-2">{labels[key]}</th>)}</tr></thead><tbody>
        {Object.entries(page.summary.excluded).map(([traffic, counts]) => <tr key={traffic}><th>{{ test: '测试', synthetic: '合成', legacy: '旧数据', unknown: '来源不明' }[traffic as keyof typeof page.summary.excluded]}</th>{metricKeys.map(key => <td key={key} className="px-2">{counts[key]}</td>)}</tr>)}
        <tr><th>真实但未完整绑定来源（筛选前）</th>{metricKeys.map(key => <td key={key} className="px-2">{page.summary.unscopedReal[key]}</td>)}</tr>
      </tbody></table></div>
      <div role="region" aria-label="来源分组表（横向滚动）" tabIndex={0} className="max-w-full overflow-x-auto rounded border border-slate-200">
        <table className="w-max min-w-full text-left text-sm"><caption className="text-left font-medium">本页公开来源分组（{page.groups.length}组）</caption><thead><tr>
          {['UTC日期', '题目', '题目版本', '规则版本', ...metricKeys.map(key => labels[key])].map(label => <th key={label} className="whitespace-nowrap px-2 py-1">{label}</th>)}
        </tr></thead><tbody>
        {page.groups.map(group => <tr key={JSON.stringify([group.day, group.soupId, group.puzzleVersion, group.ruleVersion])}>
          <td className="whitespace-nowrap px-2 py-1 align-top">{group.day}</td>
          <td className="px-2 py-1 align-top"><span className="block w-40 break-all">{group.soupId ?? '未知'}</span></td>
          <td className="px-2 py-1 align-top"><span className="block w-72 break-all font-mono">{group.puzzleVersion ?? '未知'}</span></td>
          <td className="px-2 py-1 align-top"><span className="block w-72 break-all font-mono">{group.ruleVersion ?? '未知'}</span></td>
          {metricKeys.map(key => <td key={key} className="whitespace-nowrap px-2 py-1 align-top">{group.counts[key]}</td>)}
        </tr>)}
      </tbody></table></div>
      {page.groups.length === 0 && <p>当前区间没有明确真实流量的分组。</p>}
    </div>}
  </section>;
}
