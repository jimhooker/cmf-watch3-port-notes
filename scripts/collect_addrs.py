#!/usr/bin/env python3
"""Collect the Watch Pro 2 firmware addresses hard-coded in the cmf-watch-sdk source.

Addresses in code and in comments are both recorded ("where" says which); only the code ones count as
dependencies. Handles 0x1234_5678 underscore literals and the offset-style HEAP_LITERALS tuple.

usage: collect_addrs.py SDK_REPO OUT_JSON
"""
import json
import re
import sys
from pathlib import Path

HEXRAW = re.compile(r"0x[0-9A-Fa-f][0-9A-Fa-f_]*")


class _Hex:
    @staticmethod
    def findall(text):
        out = []
        for h in HEXRAW.findall(text):
            d = h[2:].replace("_", "")
            if len(d) == 8:
                out.append("0x" + d)
        return out


HEX = _Hex
NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[A-Za-z0-9_\[\]; ()&']+)?\s*=\s*[^=]")


def split_comment(line, suffix):
    if suffix in (".rs", ".ld", ".x"):
        i = line.find("//")
        return (line, "") if i < 0 else (line[:i], line[i:])
    if suffix == ".py":
        i = line.find("#")
        return (line, "") if i < 0 else (line[:i], line[i:])
    return line, ""


def main():
    repo = Path(sys.argv[1])
    out = []
    files = []
    for sub in ("fw", "src", "sdk"):
        for p in sorted((repo / sub).rglob("*")):
            if p.is_file() and p.suffix in (".rs", ".py", ".ld", ".x", ".toml") and "/target/" not in str(p):
                files.append(p)
    for p in files:
        rel = str(p.relative_to(repo))
        in_doc = False
        in_block = False
        for ln, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            code, comment = split_comment(line, p.suffix)
            if p.suffix == ".py":
                q = code.count('"""') + code.count("'''")
                if in_doc:
                    comment = code + comment
                    code = ""
                    if q % 2 == 1:
                        in_doc = False
                elif q % 2 == 1:
                    in_doc = True
                    comment = code + comment
                    code = ""
                elif q:
                    comment = code + comment
                    code = ""
            if p.suffix in (".ld", ".rs"):
                if in_block:
                    comment = code + comment
                    code = ""
                    if "*/" in line:
                        in_block = False
                elif "/*" in code:
                    if "*/" not in code:
                        in_block = True
                    comment = code[code.find("/*"):] + comment
                    code = code[:code.find("/*")]
            m = NAME.search(code)
            name = m.group(1) if m else ""
            for h in HEX.findall(code):
                out.append({"file": rel, "line": ln, "name": name, "addr": int(h, 16), "where": "code", "text": line.strip()[:160]})
            for h in HEX.findall(comment):
                out.append({"file": rel, "line": ln, "name": "", "addr": int(h, 16), "where": "comment", "text": line.strip()[:160]})
    # firmware.py also keeps three literal-pool slots as file offsets rather than addresses
    fw_py = repo / "src" / "wp2apps" / "firmware.py"
    if fw_py.exists():
        for ln, line in enumerate(fw_py.read_text(errors="replace").splitlines(), 1):
            m = re.match(r"\s*HEAP_LITERALS\s*=\s*\(([^)]*)\)", line)
            if m:
                for tok in m.group(1).split(","):
                    tok = tok.strip()
                    if tok:
                        out.append({"file": "src/wp2apps/firmware.py", "line": ln, "name": "HEAP_LITERALS",
                                    "addr": 0x10000000 + int(tok, 0), "where": "code", "text": line.strip()[:160]})
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
    code = [o for o in out if o["where"] == "code"]
    print("files scanned", len(files), "hex8 in code", len(code), "distinct", len({o["addr"] for o in code}),
          "| in comments only", len({o["addr"] for o in out if o["where"] == "comment"} - {o["addr"] for o in code}))


if __name__ == "__main__":
    main()
