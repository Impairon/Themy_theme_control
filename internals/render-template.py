#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path

src, dst, palette = sys.argv[1:]
data = json.loads(Path(palette).read_text(encoding="utf-8"))
mode = os.environ.get("THEMY_MODE", "dark")


def extract_color(v):
    if isinstance(v, str):
        v = v.strip()
        if v.startswith("#") or (
            len(v) in (6, 8) and all(c in "0123456789abcdefABCDEF" for c in v)
        ):
            return v if v.startswith("#") else "#" + v
        return v
    if isinstance(v, dict):
        for k in ("hex", "color", "hex_stripped"):
            if k in v:
                return extract_color(v[k])
        if all(k in v for k in ("red", "green", "blue")):
            return "#%02x%02x%02x" % (int(v["red"]), int(v["green"]), int(v["blue"]))
        if "default" in v:
            return extract_color(v["default"])
    return None


def lookup(path):
    # 1. Exact path traversal if the JSON structure matches literally
    cur = data
    parts = path.split(".")
    found_exact = True
    for part in parts:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            found_exact = False
            break
    if found_exact and cur is not None:
        c = extract_color(cur)
        if c:
            return c
        if not isinstance(cur, (dict, list)):
            return str(cur)

    # 2. Extract semantic role: e.g. colors.background.default.hex -> background
    role_parts = [
        p
        for p in parts
        if p not in ("colors", "default", "hex", "themy", "dark", "light")
    ]
    role = role_parts[0] if role_parts else parts[-1]

    colors_dict = (
        data.get("colors")
        if isinstance(data, dict) and isinstance(data.get("colors"), dict)
        else data
    )

    # Check mode bucket (e.g. data['colors']['dark'][role])
    for m in (mode, "dark" if mode == "light" else "light", "default", "amoled"):
        if isinstance(colors_dict, dict) and m in colors_dict and isinstance(colors_dict[m], dict):
            val = extract_color(colors_dict[m].get(role))
            if val:
                return val

    # Check direct role (e.g. data['colors'][role])
    if isinstance(colors_dict, dict) and role in colors_dict:
        val = extract_color(colors_dict[role])
        if val:
            return val

    # Recursive fallback search across the whole tree
    def deep_search(node):
        if isinstance(node, dict):
            if role in node:
                c = extract_color(node[role])
                if c:
                    return c
            for v in node.values():
                res = deep_search(v)
                if res:
                    return res
        elif isinstance(node, list):
            for item in node:
                res = deep_search(item)
                if res:
                    return res
        return None

    
    # Fallback for container / variant roles if missing
    if role.endswith("_container"):
        base_role = role[:-10]
        base_val = lookup(f"colors.{base_role}.default.hex")
        if base_val:
            return base_val
    if role.endswith("_variant"):
        base_role = role[:-8]
        base_val = lookup(f"colors.{base_role}.default.hex")
        if base_val:
            return base_val

    return deep_search(data)



missing = []


def repl(m):
    key = m.group(1).strip()
    v = lookup(key)
    if v is None:
        missing.append(key)
        return ""
    return str(v)


text = re.sub(r"\{\{\s*([^}]+?)\s*\}\}", repl, Path(src).read_text(encoding="utf-8"))
if "{{" in text:
    raise SystemExit(f"unresolved template placeholders in {src}")
if missing:
    names = ", ".join(sorted(set(missing)))
    raise SystemExit(f"missing palette values for {src}: {names}")

dst_path = Path(dst)
dst_path.parent.mkdir(parents=True, exist_ok=True)
dst_path.write_text(text, encoding="utf-8")
