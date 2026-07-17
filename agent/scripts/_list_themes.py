import ast
from pathlib import Path
from collections import Counter

theme_counter = Counter()
theme_to_ids = {}

zoo = Path(__file__).resolve().parent.parent / "src" / "factors" / "zoo" / "gtja191"
for f in sorted(zoo.glob("alpha_*.py")):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__alpha_meta__":
                    meta = ast.literal_eval(node.value)
                    themes = meta.get("theme", [])
                    aid = meta.get("id", f.stem)
                    for th in themes:
                        theme_counter[th] += 1
                        theme_to_ids.setdefault(th, []).append(aid)

print(f"Total theme tags: {sum(theme_counter.values())}, unique themes: {len(theme_counter)}\n")
print(f"{'Theme':<25} {'Count':<8}  Sample IDs")
print("-" * 90)
for theme, cnt in theme_counter.most_common():
    ids = theme_to_ids[theme]
    sample = ", ".join(ids[:5])
    ellipsis = "..." if len(ids) > 5 else ""
    print(f"{theme:<25} {cnt:<8}  {sample}{ellipsis}")
