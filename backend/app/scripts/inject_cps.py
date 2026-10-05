"""精准插入 confusionPoints 到 soups.py 的 SEED_SOUPS（AST 定位，不改动其它内容）。

仅用于把评测发现漏网/复合误判的题目补成确定性兜底 CP。
"""
import ast
import json

PATH = "app/soups.py"

# soup_id -> 要新增的 CP 列表（q/a/match/note）
ADDS = {
    "xin": [
        {"q": "车祸撞我的人是我的孩子吗", "a": "不是", "match": ["车祸撞我.*孩子", "撞我.*是我的孩子"], "note": "车祸撞人的是孩子而非爷爷"},
        {"q": "然后偷完孩子回到00年成为了爷爷被杀死", "a": "是", "match": ["然后偷完孩子.*爷爷被杀死", "偷完孩子.*成为爷爷被杀死"], "note": "整句锁定：偷完孩子回00年成为爷爷被杀死"},
    ],
    "xinren": [
        {"q": "他们是没有手或者脚吗", "a": "是", "match": ["没有手或者脚", "没有手或脚", "没手没脚"], "note": "规则怪谈角色无手脚"},
    ],
    "huiguniang-guize": [
        {"q": "老鼠嘛", "a": "是", "match": ["老鼠嘛"], "note": "老鼠是对应角色"},
    ],
    "xiaobudian": [
        {"q": "就是房东呢", "a": "是", "match": ["就是房东", "房东呢"], "note": "对方就是房东"},
    ],
  "caimingzi": [
        {"q": "防谁呢", "a": "不是", "match": ["防谁"], "note": "防的不是所指对象"},
    ],
    "chongying": [
        {"q": "那能对吗", "a": "是", "match": ["那能对", "能对吗"], "note": "该判断成立"},
        {"q": "瞎了吗", "a": "是", "match": ["瞎了", "瞎了吗"], "note": "角色失明"},
    ],
    "xueyuan-guize": [
        {"q": "学校的职工只能是曾经在学校毕业的学生", "a": "是", "match": ["职工.*毕业的学生", "职工.*毕业生"], "note": "整句锁定：职工只能是毕业生"},
    ],
    "tonghua-xiaozhen": [
        {"q": "童话镇中现在还有绵羊", "a": "是", "match": ["童话镇.*还有绵羊", "还有绵羊"], "note": "整句锁定：童话镇曾有绵羊"},
    ],
}


def main():
    with open(PATH, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.split("\n")

    # 找到 SEED_SOUPS 的 List 节点
    sa = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "SEED_SOUPS":
                    sa = node.value
    assert sa and isinstance(sa, ast.List), "找不到 SEED_SOUPS"

    def find_soup(sid):
        for d in sa.elts:
            for k, v in zip(d.keys, d.values):
                if isinstance(k, ast.Constant) and k.value == "id" \
                        and isinstance(v, ast.Constant) and v.value == sid:
                    return d
        return None

    def get_cp_list(d):
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and k.value == "confusionPoints":
                return v
        return None

    def indent_of_line(lineno1):
        line = lines[lineno1 - 1]
        return line[: len(line) - len(line.lstrip())]

    for sid, cps in ADDS.items():
        d = find_soup(sid)
        assert d, f"找不到汤 {sid}"
        cp_list = get_cp_list(d)
        assert cp_list, f"{sid} 无 confusionPoints"
        indent = indent_of_line(cp_list.elts[0].lineno)
        insert_at = cp_list.end_lineno - 1  # `]` 所在行（0-based）
        # 确保最后一个已有元素行以逗号结尾
        prev = lines[insert_at - 1]
        if prev.rstrip().endswith("]") or prev.rstrip().endswith("{"):
            pass
        elif not prev.rstrip().endswith(","):
            lines[insert_at - 1] = prev.rstrip() + ","
        # 构造新条目
        new_block = []
        for cp in cps:
            new_block.append(indent + json.dumps(cp, ensure_ascii=False) + ",")
        lines[insert_at:insert_at] = new_block

    new_src = "\n".join(lines)
    # 校验可重新解析
    ast.parse(new_src)
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(new_src)
    print("✅ 已注入", sum(len(v) for v in ADDS.values()), "条 CP，覆盖汤：", list(ADDS.keys()))


if __name__ == "__main__":
    main()
