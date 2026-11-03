#!/usr/bin/env python3
"""文档体系工具：生成 INDEX、检查元数据与合规、自动修复。

在仓库根目录运行：

    python scripts/docs.py index     # 生成 docs/INDEX.md
    python scripts/docs.py check     # CI 用；有阻断项时退出码 1
    python scripts/docs.py fix       # 自动补 front-matter、补小节、重建 INDEX

只依赖标准库。front-matter 只支持两种写法：

    key: value
    key: [a, b]

不支持的 YAML 特性一律当作错误，宁可报错也不要猜。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "INDEX.md"
FORBIDDEN_FILE = ROOT / "scripts" / "forbidden_words.txt"
OWNERS_FILE = ROOT / "scripts" / "owners.txt"

REQUIRED = ("title", "owner", "status", "last_updated", "summary", "audience")
STATUS_OK = {"draft", "review", "final"}
AUDIENCE_OK = {"human", "agent", "both"}

# 合规：命中即阻断，不提供自动修复（内容必须人来改）
SECRETS = (
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "疑似模型 API 密钥（sk- 开头）"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "疑似 GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "疑似 AWS Access Key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "疑似私钥"),
)
PII = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "疑似真实手机号（脱敏写法：138****0000）"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "疑似身份证号"),
)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

GROUPS = (
    ("核心文档", None),
    ("模块文档", "modules"),
    ("决策记录", "decisions"),
    ("任务回执", "reports"),
    ("任务单", "tickets"),
    ("归档", "archive"),
)
REPORT_SECTIONS = ("做了什么", "没做完", "下次接手", "怎么验收")

MAX_LINES = 800
STALE_DAYS = 90


# ---------------------------------------------------------------- 基础工具


def out(text: str = "") -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 老环境没有 reconfigure
        pass
    print(text)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").lstrip("\ufeff")


def write_text(path: Path, text: str) -> None:
    """统一按 LF 写盘。Windows 上 write_text 默认转 CRLF，会让 INDEX 永远显示已修改。"""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_front_matter(text: str):
    """返回 (dict, 状态, 正文起始行号)。状态：ok / missing / malformed。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "missing", 1
    for i in range(1, len(lines)):
        if lines[i].strip() != "---":
            continue
        data: dict[str, str] = {}
        for raw in lines[1:i]:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if ":" not in s:
                return {}, "malformed", 1
            key, value = s.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
        return data, "ok", i + 2
    return {}, "malformed", 1


def dump_front_matter(data: dict[str, str]) -> str:
    order = list(REQUIRED) + [k for k in data if k not in REQUIRED]
    body = "\n".join(f"{k}: {data[k]}" for k in order if k in data)
    return f"---\n{body}\n---\n"


def iter_docs() -> list[Path]:
    if not DOCS.is_dir():
        return []
    return sorted(
        p for p in DOCS.rglob("*.md") if p.is_file() and p.name != "INDEX.md"
    )


def rel_of(path: Path) -> str:
    return path.relative_to(DOCS).as_posix()


def is_template(path: Path) -> bool:
    name = path.name
    return name.startswith("_") or name.startswith("模板")


def load_forbidden() -> list[str]:
    if not FORBIDDEN_FILE.is_file():
        return []
    words = []
    for raw in read_text(FORBIDDEN_FILE).splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            words.append(s)
    return words


def load_owners() -> list[str]:
    if not OWNERS_FILE.is_file():
        return []
    owners = []
    for raw in read_text(OWNERS_FILE).splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            owners.append(s)
    return owners


def default_meta(path: Path, text: str) -> dict[str, str]:
    title = path.stem
    summary = "（待补一句话说明）"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
            break
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("> ") and len(s) > 4:
            summary = s[2:].strip()
            if len(summary) > 80:
                summary = summary[:80] + "…"
            break
    return {
        "title": title,
        "owner": "",
        "status": "draft",
        "last_updated": dt.date.today().isoformat(),
        "summary": summary,
        "audience": "agent",
    }


# ---------------------------------------------------------------- 检查


def check_file(path: Path, forbidden: list[str], today: dt.date, owners: list[str]):
    """返回 issue 列表：dict(path, line, level, msg)。level: block / warn"""
    issues: list[dict] = []
    rel = rel_of(path)
    text = read_text(path)
    lines = text.splitlines()

    def add(line: int, level: str, msg: str) -> None:
        issues.append({"path": rel, "line": line, "level": level, "msg": msg})

    meta, state, body_line = read_front_matter(text)
    if state == "missing":
        add(1, "block", "缺少 front-matter（文件第一行必须是 ---）")
    elif state == "malformed":
        add(1, "block", "front-matter 不合法：字段必须是 `key: value` 且以 --- 结尾")
    else:
        for key in REQUIRED:
            if key not in meta:
                add(1, "block", f"front-matter 缺字段 {key}")
        if meta.get("status") and meta["status"] not in STATUS_OK:
            add(1, "block", f"status 只能是 {'/'.join(sorted(STATUS_OK))}，当前={meta['status']}")
        if meta.get("audience") and meta["audience"] not in AUDIENCE_OK:
            add(1, "block", f"audience 只能是 {'/'.join(sorted(AUDIENCE_OK))}，当前={meta['audience']}")
        owner = meta.get("owner", "")
        if not owner:
            add(1, "block", "owner 不能为空：填代号（队长/A/B/C/D，见 scripts/owners.txt）")
        elif owners and owner not in owners:
            add(1, "block", f"owner「{owner}」不在代号表里（可用：{' / '.join(owners)}）")
        stamp = meta.get("last_updated", "")
        if stamp:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
                add(1, "block", f"last_updated 必须写成 YYYY-MM-DD，当前={stamp}")
            else:
                try:
                    age = (today - dt.date.fromisoformat(stamp)).days
                except ValueError:
                    age = -1
                if age < 0:
                    add(1, "warn", f"last_updated 在未来（{stamp}）")
                elif meta.get("status") == "final" and age > STALE_DAYS:
                    add(1, "warn", f"status=final 但已 {age} 天未更新，建议复核")

    in_fence = False
    for no, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if no < body_line:
            continue
        for pattern, label in SECRETS:
            if pattern.search(line):
                add(no, "block", f"{label}，删掉后再提交")
        for pattern, label in PII:
            if pattern.search(line):
                add(no, "block", f"{label}，改成脱敏示例")
        for word in forbidden:
            if word in line:
                add(no, "block", f"命中竞赛匿名词「{word}」，删掉或改成泛称")
        if in_fence:
            continue
        for target in LINK.findall(line):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            rel_target = target.split("#", 1)[0]
            if not rel_target:
                continue
            if not (path.parent / rel_target).exists():
                add(no, "block", f"链接指向不存在的文件：{target}")

    if len(lines) > MAX_LINES:
        add(1, "warn", f"文档 {len(lines)} 行，超过 {MAX_LINES} 行的上限，建议拆进 modules/")

    if rel.startswith("reports/") and not is_template(path):
        for section in REPORT_SECTIONS:
            if not any(section in line for line in lines[body_line - 1 :]):
                add(1, "block", f"任务回执缺少小节「{section}」")
    return issues


# ---------------------------------------------------------------- INDEX


def build_index() -> str:
    rows = []
    for path in iter_docs():
        if path.name == "INDEX.md" or is_template(path):
            continue
        meta, state, _ = read_front_matter(read_text(path))
        rows.append((rel_of(path), meta if state == "ok" else {}))

    def group_of(rel: str) -> str | None:
        if "/" not in rel:
            return None
        head = rel.split("/", 1)[0]
        for _, prefix in GROUPS:
            if prefix and head == prefix:
                return prefix
        return "other"

    parts = [
        "# 文档索引",
        "",
        "> 本文件由 `python scripts/docs.py index` 自动生成，**不要手改**。",
        "> 新增或改名文档：写好 front-matter → 跑一次 `python scripts/docs.py index` → 一起提交。",
        "> Agent 读法：先看本页，再按 `depends_on` 只读 1–3 份，总量 ≤ 600 行。",
        "",
    ]
    total = 0
    for title, prefix in GROUPS:
        group_rows = [r for r in rows if group_of(r[0]) == prefix]
        if not group_rows:
            continue
        total += len(group_rows)
        parts.append(f"## {title}（{len(group_rows)}）")
        parts.append("")
        parts.append("| 文档 | 状态 | 负责人 | 更新 | 说明 |")
        parts.append("| --- | --- | --- | --- | --- |")
        for rel, meta in group_rows:
            label = meta.get("title") or Path(rel).stem
            short = re.sub(r"（[^（）]*）\s*$", "", label).strip() or label
            parts.append(
                "| [{label}]({rel}) | {status} | {owner} | {stamp} | {summary} |".format(
                    label=short,
                    rel=rel,
                    status=meta.get("status", "—"),
                    owner=meta.get("owner", "—"),
                    stamp=meta.get("last_updated", "—"),
                    summary=(meta.get("summary") or "—").replace("|", "/"),
                )
            )
        parts.append("")
    others = [r for r in rows if group_of(r[0]) == "other"]
    if others:
        parts.append(f"## 其他（{len(others)}）")
        parts.append("")
        for rel, meta in others:
            parts.append(f"- [{meta.get('title') or rel}]({rel})")
        parts.append("")
        total += len(others)
    parts.append(f"<!-- 共 {total} 份；模板（下划线或“模板”开头）不计入索引 -->")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------- 命令


def cmd_index(_args) -> int:
    text = build_index()
    write_text(INDEX, text)
    out(f"已生成 {INDEX.relative_to(ROOT).as_posix()}")
    return 0


def cmd_check(_args) -> int:
    forbidden = load_forbidden()
    owners = load_owners()
    today = dt.date.today()
    issues: list[dict] = []
    for path in iter_docs():
        issues.extend(check_file(path, forbidden, today, owners))

    expected = build_index()
    if not INDEX.is_file():
        issues.append({"path": "docs/INDEX.md", "line": 1, "level": "block", "msg": "索引文件不存在"})
    elif read_text(INDEX) != expected:
        issues.append(
            {
                "path": "docs/INDEX.md",
                "line": 1,
                "level": "block",
                "msg": "索引与磁盘不一致（跑 python scripts/docs.py index）",
            }
        )

    blocks = [i for i in issues if i["level"] == "block"]
    warns = [i for i in issues if i["level"] == "warn"]
    for item in sorted(issues, key=lambda i: (i["path"], i["line"], i["level"])):
        mark = "✗" if item["level"] == "block" else "!"
        out(f"{mark} {item['path']}:{item['line']}  {item['msg']}")

    if blocks:
        out()
        out(f"FAIL  阻断 {len(blocks)} 项 / 警告 {len(warns)} 项")
        out("修复：python scripts/docs.py fix   （能自动修的它会修，匿名词与密钥必须人工改）")
        return 1
    out(f"OK    阻断 0 / 警告 {len(warns)} 项")
    return 0


def cmd_fix(_args) -> int:
    today = dt.date.today().isoformat()
    changed = 0
    for path in iter_docs():
        text = read_text(path)
        meta, state, body_line = read_front_matter(text)
        lines = text.splitlines()
        if state == "malformed":
            out(f"跳过 {rel_of(path)}：front-matter 格式错，需人工改")
            continue
        if state == "missing":
            head = dump_front_matter(default_meta(path, text))
            write_text(path, head + "\n" + text)
            out(f"补 front-matter：{rel_of(path)}")
            changed += 1
            continue
        filled = dict(meta)
        default = default_meta(path, text)
        touched = False
        for key in REQUIRED:
            if not filled.get(key):
                if key == "owner":
                    out(f"需要手填 owner：{rel_of(path)}  （可选：队长 / A / B / C / D）")
                    continue
                filled[key] = today if key == "last_updated" else default[key]
                touched = True
        if filled.get("status") not in STATUS_OK:
            filled["status"] = "draft"
            touched = True
        if filled.get("audience") not in AUDIENCE_OK:
            filled["audience"] = "agent"
            touched = True
        if not touched:
            pass
        else:
            body = "\n".join(lines[body_line - 1 :])
            write_text(path, dump_front_matter(filled) + "\n" + body)
            out(f"补字段：{rel_of(path)}")
            changed += 1

        if rel_of(path).startswith("reports/") and not is_template(path):
            content = read_text(path)
            missing = [s for s in REPORT_SECTIONS if s not in content]
            if missing:
                addition = "".join(f"\n## {s}\n（待补）\n" for s in missing)
                write_text(path, content.rstrip() + "\n" + addition)
                out(f"补小节：{rel_of(path)} → {', '.join(missing)}")
                changed += 1

    write_text(INDEX, build_index())
    out(f"已重建 docs/INDEX.md；共改动 {changed} 处")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="文档体系工具（index / check / fix）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="生成 docs/INDEX.md").set_defaults(func=cmd_index)
    sub.add_parser("check", help="检查元数据、死链、合规（CI 用）").set_defaults(func=cmd_check)
    sub.add_parser("fix", help="自动补 front-matter、补小节、重建索引").set_defaults(func=cmd_fix)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
