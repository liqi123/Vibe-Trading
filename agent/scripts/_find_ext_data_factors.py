"""找出GTJA因子中被降级的（需要外部数据但实际不可用）。"""
import ast
from pathlib import Path

zoo = Path(__file__).resolve().parent.parent / "src" / "factors" / "zoo" / "gtja191"

for f in sorted(zoo.glob("alpha_*.py")):
    src = f.read_text(encoding="utf-8")
    tree = ast.parse(src)
    meta = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__alpha_meta__":
                    meta = ast.literal_eval(node.value)
    if meta is None:
        continue
    notes = meta.get("notes", "")
    # factors where compute was degraded due to missing data
    degraded_keywords = ["degraded", "approximated", "truncated", "proxy", "unavailable", "not implementable"]
    is_degraded = any(kw in notes.lower() for kw in degraded_keywords)
    if is_degraded:
        theme = ", ".join(meta.get("theme", []))
        cols = ", ".join(meta.get("columns_required", []))
        print(f"{f.stem:20s}  theme={theme:25s}  cols=[{cols}]\n   note={notes[:120]}")
