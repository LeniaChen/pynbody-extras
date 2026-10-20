#!/usr/bin/env python3
"""Archive a completed work item into the monthly bilingual history ledger."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "docs" / "work"
HISTORY = ROOT / "docs" / "history"
PYPROJECT = ROOT / "pyproject.toml"
ID_RE = re.compile(r"\b(?:REQ|FEAT|BUG|TASK|SPIKE)-\d{4}\b")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repo_url() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^Repository\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("pyproject.toml has no [project.urls] Repository")
    return match.group(1).rstrip("/")


def header(month: str, *, chinese: bool) -> str:
    if chinese:
        return (
            f"# 历史记录 — {month}\n\n"
            f"[English]({month}.md) | [简体中文]({month}.zh-CN.md)\n\n"
            "已归档工作项。Commit 链接指向最后一个仍包含 "
            "`docs/work/<ID>/` 完整记录的提交。\n\n"
            "| 日期 | ID | 类型 | 概要 | Commit | 详情 | PR |\n"
            "|------|----|------|------|--------|------|----|\n"
        )
    return (
        f"# History — {month}\n\n"
        f"[English]({month}.md) | [简体中文]({month}.zh-CN.md)\n\n"
        "Archived work items. The commit link is the last commit that contains "
        "the full work item under `docs/work/<ID>/`.\n\n"
        "| Date | ID | Type | Summary | Commit | Details | PR |\n"
        "|------|----|------|---------|--------|---------|----|\n"
    )


def append_row(path: Path, row: str, month: str, *, chinese: bool) -> None:
    if not path.exists():
        path.write_text(header(month, chinese=chinese), encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + row + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, dest="item_id")
    args = parser.parse_args()

    folder = WORK / args.item_id
    meta_path = folder / "meta.json"
    if not meta_path.is_file():
        raise SystemExit(f"unknown work item: {folder}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("status") != "done":
        raise SystemExit("refusing to archive: status must be 'done'")

    completed = str(meta.get("completed") or "")
    if not DATE_RE.fullmatch(completed):
        raise SystemExit("refusing to archive: meta.completed must be YYYY-MM-DD")
    for filename in ("en.md", "zh-CN.md", "handoff.md"):
        if not (folder / filename).is_file():
            raise SystemExit(f"refusing to archive: {folder / filename} is missing")

    dirty = run_git("status", "--porcelain", "--", str(folder.relative_to(ROOT)))
    if dirty:
        raise SystemExit("refusing to archive: commit the completed work item first")
    head = run_git("rev-parse", "HEAD")
    run_git("cat-file", "-e", f"{head}:docs/work/{args.item_id}/meta.json")

    for path in HISTORY.glob("*.md"):
        if path.name.startswith("README"):
            continue
        if re.search(rf"\b{re.escape(args.item_id)}\b", path.read_text(encoding="utf-8")):
            raise SystemExit(f"refusing to archive: {args.item_id} is already in {path}")

    month = completed[:7]
    en_path = HISTORY / f"{month}.md"
    zh_path = HISTORY / f"{month}.zh-CN.md"
    base = repo_url()
    short = head[:7]
    commit_link = f"[{short}]({base}/commit/{head})"
    details_en = f"[work item]({base}/tree/{head}/docs/work/{args.item_id})"
    details_zh = f"[工作项]({base}/tree/{head}/docs/work/{args.item_id})"
    if meta.get("pr"):
        pr_number = int(meta["pr"])
        pr_link = f"[#{pr_number}]({base}/pull/{pr_number})"
    elif meta.get("issue"):
        pr_number = int(meta["issue"])
        pr_link = f"[#{pr_number}]({base}/issues/{pr_number})"
    else:
        pr_link = "—"

    title_en = str(meta.get("title_en", "")).replace("|", "\\|")
    title_zh = str(meta.get("title_zh", "")).replace("|", "\\|")
    en_row = (
        f"| {completed} | {args.item_id} | {meta['type']} | {title_en} | "
        f"{commit_link} | {details_en} | {pr_link} |"
    )
    zh_row = (
        f"| {completed} | {args.item_id} | {meta['type']} | {title_zh} | "
        f"{commit_link} | {details_zh} | {pr_link} |"
    )

    append_row(en_path, en_row, month, chinese=False)
    append_row(zh_path, zh_row, month, chinese=True)
    shutil.rmtree(folder)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_index.py")], check=True, cwd=ROOT)

    print(f"archived {args.item_id} at {head}")
    print(f"history: {en_path.relative_to(ROOT)}")
    print(f"history: {zh_path.relative_to(ROOT)}")
    print(f"deleted: {folder.relative_to(ROOT)}")
    print("review `git diff` and commit the history row plus the deletion.")


if __name__ == "__main__":
    main()
