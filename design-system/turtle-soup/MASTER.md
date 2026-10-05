# 设计系统 · 许二木海龟汤自助

> 全局唯一事实来源（Global Source of Truth）。所有页面、组件、配色、字体、间距、状态、响应式与可访问性规则以此为准。
> 派生自 UI/UX Pro Max 技能的设计原则 + 已验证的暗色悬疑/电影感配色与 "Classic Elegant" 字体配对。

---

## 0. 决策记录（为什么要这样设计）

- **产品类型**：海龟汤（横向思维推理）谜题游戏，AI 主持；标签含悬疑/心理/恐怖/情感。本质是**沉浸式悬疑叙事娱乐产品**。
- **页面类型**：① 大厅（汤品选择）② 难度选择 ③ 游戏（汤面 + 聊天双栏）。
- **风格要求**：暗夜、悬疑、故事感、沉浸；与现有「amber 暖金 + 深墨底」品牌一致。
- **技能自动匹配的 "Claymorphism + 粉色" 被显式否决**：该系统偏儿童/教育/休闲，关键词 playful/toy-like，与悬疑沉浸调性冲突。改为**暗色电影感（dark-noir cinematic）+ 衬线展示字（editorial serif）**，配色与字体均来自技能已验证数据库（Theater/Cinema 暗色调色板、Classic Elegant 字体配对）。
- **单主题（Dark-first）**：不做亮色模式。理由：悬疑沉浸品类天生暗色；现有代码已是暗色硬编码。统一用显式暗色 token，移除 `dark:` 双套写法，避免不一致。
- **零额外网络字体依赖（中文）**：Playfair Display / Inter 仅覆盖拉丁字符（用 `next/font` 自托管，构建期下载一次）；中文回退到系统字体（PingFang SC / Microsoft YaHei / Noto Sans SC），零运行时请求、无 CLS。

---

## 1. 设计 Dial

| Dial | 取值 | 说明 |
|------|------|------|
| Variance | 4/10 | 平衡现代，不夸张 |
| Motion | 3/10 | 克制的微交互（悬疑品类不宜花哨） |
| Density | 5/10 | 标准间距 |

---

## 2. 色彩令牌（Color Tokens）

> 全部为暗色。对比度均以 `#0B0B12`(canvas) 为基准校验，正文/次要文字 ≥ 4.5:1（WCAG AA）。

### 2.1 基础 / 表面 / 边框
| 令牌 | 值 | Tailwind 工具类 | 用途 | 对比度(on canvas) |
|------|-----|----------------|------|-------------------|
| `--color-canvas` | `#0B0B12` | `bg-canvas` | 页面底色（深墨近黑，略带靛蓝） | — |
| `--color-surface` | `#15151F` | `bg-surface` | 卡片 / 一级面板 | — |
| `--color-surface-2` | `#1C1C28` | `bg-surface-2` | 嵌套面板 / 输入区底 | — |
| `--color-elevated` | `#20202E` | `bg-elevated` | 弹窗 / 浮层 | — |
| `--color-border` | `#2A2A3A` | `border-border` | 默认边框 | — |
| `--color-border-strong` | `#3A3A4D` | `border-border-strong` | 输入框边框 / 强调分隔 | — |

### 2.2 文字
| 令牌 | 值 | 工具类 | 用途 | 对比度 |
|------|-----|--------|------|--------|
| `--color-fg` | `#F4F4F8` | `text-fg` | 主文字 / 标题 | ~18:1 ✅ |
| `--color-fg-muted` | `#C4C4D0` | `text-fg-muted` | 次要文字 / 标签 | ~11:1 ✅ |
| `--color-fg-subtle` | `#8E8E9E` | `text-fg-subtle` | 三级提示 / 占位符 | ~6.1:1 ✅ |

> ⚠️ 禁止使用 `zinc-500/600`、`text-zinc-600/700` 作为暗底上的正文/提示（对比度 < 4.5:1，违反 AA）。旧代码中的 `text-zinc-500/600` 一律升级到 `text-fg-muted`/`text-fg-subtle`。

### 2.3 品牌强调（暖金 amber）
| 令牌 | 值 | 工具类 | 用途 |
|------|-----|--------|------|
| `--color-accent` | `#F59E0B` | `bg-accent` | 实心填充按钮底色（暖金） |
| `--color-accent-fg` | `#1A1206` | `text-accent-fg` | 实心填充上的文字（深暖黑） |
| `--color-accent-text` | `#FBBF24` | `text-accent-text` | 暗底上的金色文字 / 边框（更亮，暗底可读） |
| `--color-ring` | `#FBBF24` | `ring-ring` | 焦点环（金色，键盘可见） |

### 2.4 语义色
| 令牌 | 值 | 工具类 | 用途 |
|------|-----|--------|------|
| `--color-success` | `#34D399` | `text-success`/`bg-success` | 「是」/ 不限次 / 已触及关键点 |
| `--color-danger` | `#F87171` | `text-danger`/`bg-danger` | 次数耗尽 / 未触及关键点 / 错误（暗底上加亮红） |
| `--color-danger-strong` | `#EF4444` | — | 危险实心填充（如确认） |

### 2.5 Tag 配色（标签徽章）
标签采用「半透明底 + 明亮文字 + 细边框」，文字色均 ≥ 4.5:1（emerald/sky/purple/rose/amber/red/indigo/cyan/orange/blue/teal 的 400 档）。集中维护在 `SoupCard` 的 `TAG_STYLES` 映射，结构统一为 `bg-{c}-500/10 text-{c}-400 border-{c}-500/20`。

---

## 3. 字体（Typography）

| 角色 | 字体栈 | 工具类 | 说明 |
|------|--------|--------|------|
| Display（标题/Logo/汤标题/弹窗标题） | `'Noto Serif SC', 'Songti SC', 'STSong', Georgia, serif` | `font-display` | 衬线，文学/悬疑/故事感；中文用系统衬线（Songti/Noto Serif SC），拉丁回退 Georgia |
| Body（所有正文/UI） | `system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif` | `font-sans`（默认） | 系统无衬线，中文 PingFang SC / Microsoft YaHei |

- 基准字号 **16px**，正文 `line-height: 1.6`；标题 `tracking-tight`、行高紧凑。
- **实现选择：纯系统字体栈，零网络依赖。** 初版方案用过 `next/font/google`（自托管 Inter/Playfair），但构建环境/部署机未必能访问 Google Fonts，会导致 `next build` 失败；改为纯系统字体栈后构建稳定、离线可跑、无 CLS。中文标题走系统衬线（Songti SC / Noto Serif SC）仍能呈现文学/悬疑质感。若日后要更强拉丁衬线，可在有网络处用 `next/font` 自托管 Playfair Display 并加为 `font-display` 栈首项。
- **禁止** `< 12px` 的正文；装饰性小字（如 `text-[10px]` 完成度标注）仅用于非必要信息且颜色 ≥ subtle。

---

## 4. 间距 / 圆角 / 阴影

- **间距**：以 4px 为基准（Tailwind 默认尺度）。统一：页面 `px-6 py-10`、卡片 `p-5/p-6`、栅格 `gap-5`、区块 `space-y-4`。
- **圆角**：卡片 `rounded-2xl`(16px)、面板/输入/按钮 `rounded-xl`(12px)、胶囊/徽章 `rounded-full`。
- **阴影**：暗色下用 `shadow-2xl shadow-black/40` + 边框代替纯阴影；隐藏彩蛋/强调用 `shadow-accent/10`。避免硬阴影。

---

## 5. 组件状态规范（Component States）

统一使用 `@layer components` 中的工具类，禁止在各处手写散落的 hover/transition：

| 类 | 结构 | 状态 |
|----|------|------|
| `.btn` | inline-flex 居中、gap-2、rounded-xl、px-4 py-2.5、transition 200ms、cursor-pointer | hover 微调 / active:scale-95 / **focus-visible:ring-2 ring-ring** / disabled:opacity-40 disabled:cursor-not-allowed |
| `.btn-accent` | 金色调 | `bg-accent/10 border border-accent/30 text-accent-text` → hover `bg-accent/20 border-accent/50` |
| `.btn-ghost` | 中性 | `border-border text-fg-muted` → hover `bg-surface-2 text-fg` |
| `.card` | `bg-surface border-border rounded-2xl` | hover `-translate-y-1 shadow-2xl`（仅大厅卡片） |
| `.panel` | `bg-surface-2 border-border rounded-xl` | — |
| `.input` | `bg-canvas border-border-strong rounded-xl px-4 py-3 text-fg placeholder-fg-subtle` | focus-visible `border-accent/50 ring-2 ring-accent/20` |
| `.tag` | `rounded-full border px-2 py-0.5 text-xs` + TAG_STYLES | — |

**所有可点击元素必须**：`cursor-pointer` + 可见 `focus-visible` 焦点环 + ≥ 44×44px 触摸区（按钮 `min-h-11`，输入 `min-h-12`）。

---

## 6. 图标规范（Icons）

- **禁止 emoji 当图标**（技能反模式）。统一使用内联 SVG（Lucide/Heroicons 风格，24×24、`currentColor`、`strokeWidth 1.75`），集中在 `src/components/icons.tsx`。
- 常用：Turtle(Logo) / Search / ArrowLeft / ArrowRight / Gift / Coffee / Mask(主持人头像) / Refresh / Flag(认输·揭晓) / Target(复盘) / Trophy(通关) / Lock / Clipboard(复盘模态) / Scroll(汤面·汤底) / Close / Check / Alert。
- **例外（不改）**：后端 AI 生成的回复前缀 `🤔/🎯/⚠️` 属内容而非 UI 图标，且被前端逻辑 `startsWith` 判定「免费提示」，改动需后端配合，暂保留。

---

## 7. 布局 / 响应式（Responsive）

- **断点**：375 / 768 / 1024 / 1440。移动优先。
- **大厅**：`grid gap-5 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`。
- **难度页**：`grid gap-5 grid-cols-1 sm:grid-cols-3`。
- **游戏页**：手机上下堆叠（汤面置顶 `max-h-[38vh]` 可滚动，聊天在下）；`lg:` 起左右分栏（汤面 `lg:w-[38%] lg:min-w-[300px] lg:max-w-[480px]`）。根容器 `h-screen flex flex-col overflow-hidden`，**禁止横向滚动**。
- 标题响应式：`text-3xl`（移动）→ `sm:text-4xl`。
- 触摸目标 ≥ 44px；模态/浮层在移动端 `max-w-[92vw]`。

---

## 8. 可访问性（Accessibility — 最高优先级）

1. **对比度**：正文/次要文字 ≥ 4.5:1（见 §2.2 令牌，已校验）。
2. **焦点环**：所有交互元素 `focus-visible:ring-2 ring-ring ring-offset-2 ring-offset-canvas`；**绝不** `outline:none` 而无替代。
3. **键盘可达**：模态框 `role="dialog" aria-modal="true" aria-labelledby`；打开时聚焦首个可聚焦元素、Esc 关闭、关闭后焦点归还触发元素；图标按钮加 `aria-label`。
4. **减少动画**：全局 `@media (prefers-reduced-motion: reduce)` 关闭 `transform`/`animation`（spin/bounce/hover 位移），直接呈现终态。
5. **图片**：`<img>` 必须有 `alt`（赞赏码已有）。
6. **语义**：标题层级 `h1>h2>h3` 连续；列表用 `<ul>/<li>`；按钮用 `<button>` 而非 `<div>`。
7. **语言**：`<html lang="zh-CN">` 已设。

---

## 9. 反模式（Avoid）

- ❌ emoji 当图标
- ❌ 暗底上使用 `zinc-500/600` 等低对比文字
- ❌ 手写散落的 hover/transition（必须用 §5 组件类）
- ❌ 移除焦点环（`outline:none` 无替代）
- ❌ 依赖 `hover` 传达状态（触摸设备无 hover）→ 状态需常驻可见
- ❌ 固定像素容器宽度 / 禁用缩放 / 横向滚动
- ❌ 单一 duration 套用所有过渡（保持 150–300ms）
- ❌ 动画 `width/height`（用 transform/opacity）
