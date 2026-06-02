import yaml, os

base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "chatbots", "wlo", "v1", "04-personas")

def frontmatter(path):
    txt = open(path, encoding="utf-8").read()
    parts = txt.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""

for name in ["and", "elt", "ent", "leh", "ler", "red"]:
    p = os.path.join(base, name + ".md")
    try:
        d = yaml.safe_load(frontmatter(p))
        n = len((d or {}).get("positive_markers") or [])
        print(f"{name}.md: OK   id={(d or {}).get('id')}  markers={n}")
    except Exception as e:
        msg = str(e).replace("\n", " ")[:220]
        print(f"{name}.md: YAML-FEHLER -> {type(e).__name__}: {msg}")
