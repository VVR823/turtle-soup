"""自动抽取脚本：把"汤面+汤底"扩写成完整结构化汤品（收录新汤无需手工调教）。

用法：
  cd backend
  # 批量：从 data/soup_sources.json（作者只写 surface+bottom+难度）生成
  python preprocess_soup.py --source data/soup_sources.json
  # 单条：
  python preprocess_soup.py --title "新汤名称" --surface "..." --bottom "..."

输出：data/generated_soups.json（db.py 启动时自动合并加载到 SOUPS）

原理（治本的关键）：
  用一次 LLM 调用，从【完整汤底】抽取出训练 AI 主持人所需的全部结构化字段：
    - bottomSummary   ：简洁真相摘要（必须覆盖关键因果链，避免 LLM 因摘要不全而误判）
    - checkpoints     ：关键真相点（是/不是）——自动生成的 RAG 锚点
    - confusionPoints ：玩家最易误判的问题 + 标答 + 触发关键词（脚本转成正则，作确定性保险丝）
    - symbolMappings  ：汤面意象 → 真实含义（解决"字面关键词误判"）
  这样收录新汤时，作者只需写清"汤面+汤底"，跑本脚本即可，不用像双鱼汤那样逐个问题手工打补丁。
"""
import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import List

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# 让脚本能 import 同目录的 app 包
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL  # noqa: E402


class ExtractedCheckpoint(BaseModel):
    key: str = Field(description="标准问法，如'存在复制体吗'")
    answer: bool = Field(description="True=是, False=不是")
    aliases: List[str] = Field(default_factory=list, description="口语同义词，如'分身''克隆人'")


class ExtractedConfusionPoint(BaseModel):
    q: str = Field(description="玩家最可能误判的'是否类'问题，自然语言")
    a: str = Field(description="标准答案，只能是：是、不是、是也不是、算是、与此无关")
    keywords: List[str] = Field(default_factory=list, description="触发该标答的关键词列表（2-4个），脚本会转成正则")
    note: str = Field(default="", description="为什么是这个答案的简短解释")


class ExtractedSymbol(BaseModel):
    symbol: str = Field(description="汤面意象，如'鱼缸/鱼''雪地'")
    meaning: str = Field(description="真实含义")
    note: str = Field(default="", description="常见误读或判断示例")


class EnrichedFields(BaseModel):
    bottomSummary: str = Field(description="250-350字真相摘要，必须覆盖全部关键真相、因果关系与转折点")
    checkpoints: List[ExtractedCheckpoint] = Field(default_factory=list)
    confusionPoints: List[ExtractedConfusionPoint] = Field(default_factory=list)
    symbolMappings: List[ExtractedSymbol] = Field(default_factory=list)


PROMPT = """你是一个海龟汤题库构建助手。给定一道汤的[汤面]和[完整汤底]，请抽取出用于训练 AI 主持人的结构化字段。

要求：
1. bottomSummary：用 250-350 字重写汤底真相，必须覆盖全部关键真相、因果关系与转折点（如谁发了疯、为什么、关键物品的象征含义），不要遗漏会导致 AI 误判的因果链。
2. checkpoints：列出 10-15 个玩家最可能问的"是否类"关键真相点。answer 为 True 表示"是"、False 表示"不是"。aliases 是该点的口语同义表述。
3. confusionPoints：列出 6-12 个玩家最易误判的问题（如把意象当字面物品、把无关细节当因果、张冠李戴）。a 为标准答案。keywords 是触发该标答的 2-4 个关键词（用于正则匹配，顺序无关）。
   特别注意区分「是否需要/存在某物」与「目的/动机/原因」：若玩家问某行为的目的是 X，而汤底里该行为的真实动机是 Y，则应判「不是」而非「是」（如「男人要水是为了解渴吗」→不是，真实动机是止嗝；「妻子发疯是因为看到神话吗」→不是，真实原因是生下丈夫）。凡汤底明确提到某物品（如「一把枪」），问它是否真实存在应判「是」。
4. symbolMappings：列出汤面意象（物品/场景/动作）及其真实象征含义，特别指出常见误读（如把象征物误认为另一物品）。

只输出 JSON，不要任何解释或 markdown。"""

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=QWEN_MODEL,
            api_key=QWEN_API_KEY,
            base_url=QWEN_BASE_URL,
            temperature=0.2,
            max_tokens=1500,
        )
    return _llm


def _keywords_to_regex(keywords: List[str]) -> List[str]:
    """把关键词列表转成正则：双向组合，顺序无关地匹配。

    单字关键词（如'枪'）不作为独立 pattern——太宽，容易误命中无关问题
    （如'枪是真的吗'被'酒保开枪杀人'的'枪'误判成'不是'），但保留在组合 pattern 中
    （如'枪.*杀人'仍能有效命中'酒保是要开枪杀人吗'）。
    """
    if not keywords:
        return []
    multi = [re.escape(k) for k in keywords if len(k) >= 2]
    single = [re.escape(k) for k in keywords if len(k) == 1]
    patterns = list(multi)
    for i in range(len(multi)):
        for j in range(len(multi)):
            if i != j:
                patterns.append(multi[i] + ".*" + multi[j])
    for s in single:
        for m in multi:
            patterns.append(s + ".*" + m)
            patterns.append(m + ".*" + s)
    return list(dict.fromkeys(patterns))


def enrich(surface: str, bottom: str) -> dict:
    llm = _get_llm()
    parser = JsonOutputParser(pydantic_object=EnrichedFields)
    prompt = ChatPromptTemplate.from_messages([
        ("system", PROMPT),
        ("human", "汤面：{surface}\n\n完整汤底：{bottom}\n\n{format_instructions}"),
    ]).partial(format_instructions=parser.get_format_instructions())
    chain = prompt | llm | parser
    raw = chain.invoke({"surface": surface, "bottom": bottom})
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    return raw


def build_soup(source: dict) -> dict:
    fields = enrich(source["surface"], source["bottom"])
    confusion = []
    for c in fields.get("confusionPoints", []):
        confusion.append({
            "q": c.get("q", ""),
            "a": c.get("a", "与此无关"),
            "match": _keywords_to_regex(c.get("keywords", [])),
            "note": c.get("note", ""),
        })
    checkpoints = [{
        "key": c.get("key", ""),
        "answer": c.get("answer", False),
        "aliases": c.get("aliases", []),
    } for c in fields.get("checkpoints", [])]
    symbols = [{
        "symbol": s.get("symbol", ""),
        "meaning": s.get("meaning", ""),
        "note": s.get("note", ""),
    } for s in fields.get("symbolMappings", [])]
    return {
        "id": str(uuid.uuid4()),
        "title": source.get("title", "未命名"),
        "surface": source["surface"],
        "bottom": source["bottom"],
        "bottomSummary": fields.get("bottomSummary", ""),
        "checkpoints": checkpoints,
        "confusionPoints": confusion,
        "symbolMappings": symbols,
        "difficulty": source.get("difficulty", 3),
        "source": source.get("source", "auto-generated"),
        "difficultyLimits": source.get("difficultyLimits"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="soup_sources.json 路径（批量）")
    ap.add_argument("--surface", help="单条：汤面")
    ap.add_argument("--bottom", help="单条：汤底")
    ap.add_argument("--title", default="未命名")
    ap.add_argument("--out", default=str(BACKEND_DIR / "data" / "generated_soups.json"))
    args = ap.parse_args()

    sources = []
    if args.source:
        with open(args.source, encoding="utf-8") as f:
            sources = json.load(f)
    elif args.surface and args.bottom:
        sources = [{
            "title": args.title,
            "surface": args.surface,
            "bottom": args.bottom,
            "difficulty": 3,
            "source": "cli",
        }]
    else:
        print("需提供 --source 或 --surface + --bottom")
        return

    out = []
    for i, s in enumerate(sources, 1):
        print(f"[{i}/{len(sources)}] 抽取：{s.get('title', '?')}")
        try:
            out.append(build_soup(s))
        except Exception as e:
            print("  ❌ 失败:", e)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成 {len(out)} 道汤 -> {args.out}")


if __name__ == "__main__":
    main()
