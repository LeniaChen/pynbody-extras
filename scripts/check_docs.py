#!/usr/bin/env python3
"""Validate the bilingual work-item layout and the generated index."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "docs" / "work"
HISTORY = ROOT / "docs" / "history"
ID_RE = re.compile(r"^(REQ|FEAT|BUG|TASK|SPIKE)-\d{4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TYPES = {"requirement", "feature", "bug", "task", "spike"}
STATUSES = {"draft", "ready", "in-progress", "blocked", "review", "done", "archived"}
RESOLUTIONS = {"fixed", "implemented", "wontfix", "duplicate", "obsolete"}


def history_rows(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7 or cells[1] == "ID" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


def main() -> None:
    errors: list[str] = []
    seen: set[str] = set()

    for meta_path in sorted(WORK.glob("*/meta.json")):
        folder = meta_path.parent
        if folder.name.startswith("_"):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{meta_path}: invalid JSON: {exc}")
            continue

        item_id = str(meta.get("id", ""))
        if not ID_RE.fullmatch(item_id):
            errors.append(f"{meta_path}: invalid id {item_id!r}")
        if item_id in seen:
            errors.append(f"{meta_path}: duplicate id {item_id!r}")
        seen.add(item_id)
        if folder.name != item_id:
            errors.append(f"{meta_path}: folder {folder.name!r} != id {item_id!r}")
        if meta.get("type") not in TYPES:
            errors.append(f"{meta_path}: invalid type {meta.get('type')!r}")
        status = meta.get("status")
        if status not in STATUSES:
            errors.append(f"{meta_path}: invalid status {meta.get('status')!r}")
        completed = meta.get("completed")
        if completed is not None and not DATE_RE.fullmatch(str(completed)):
            errors.append(f"{meta_path}: completed must be YYYY-MM-DD or null")
        if status == "done" and completed is None:
            errors.append(f"{meta_path}: status=done requires completed")
        resolution = meta.get("resolution")
        if resolution is not None and resolution not in RESOLUTIONS:
            errors.append(f"{meta_path}: invalid resolution {resolution!r}")
        if meta.get("pr") is not None and not isinstance(meta.get("pr"), int):
            errors.append(f"{meta_path}: pr must be an integer or null")
        related = meta.get("related")
        if related is not None and (
            not isinstance(related, list) or any(not ID_RE.fullmatch(str(item)) for item in related)
        ):
            errors.append(f"{meta_path}: related must be a list of work-item IDs")
        if not str(meta.get("title_en", "")).strip():
            errors.append(f"{meta_path}: title_en is empty")
        if not str(meta.get("title_zh", "")).strip():
            errors.append(f"{meta_path}: title_zh is empty")
        if meta.get("locales") != ["en", "zh-CN"]:
            errors.append(f"{meta_path}: locales must be ['en', 'zh-CN']")
        for key in ("created", "updated"):
            if not DATE_RE.fullmatch(str(meta.get(key, ""))):
                errors.append(f"{meta_path}: {key} must be YYYY-MM-DD")

        for filename in ("en.md", "zh-CN.md"):
            path = folder / filename
            if not path.is_file() or not path.read_text(encoding="utf-8").strip():
                errors.append(f"{path}: missing or empty")
        handoff = folder / "handoff.md"
        if not handoff.is_file() or not handoff.read_text(encoding="utf-8").strip():
            errors.append(f"{handoff}: missing or empty")

    archived: set[str] = set()
    en_months = {path.name.removesuffix(".md") for path in HISTORY.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].md")}
    zh_months = {
        path.name.removesuffix(".zh-CN.md") for path in HISTORY.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].zh-CN.md")
    }
    if en_months != zh_months:
        errors.append(f"{HISTORY}: monthly English/Chinese files do not pair: {sorted(en_months ^ zh_months)}")
    for odd in HISTORY.glob("[0-9][0-9][0-9][0-9].md"):
        errors.append(f"{odd}: use a monthly file (YYYY-MM.md), not a yearly file")

    for month in sorted(en_months & zh_months):
        en_rows = history_rows(HISTORY / f"{month}.md")
        zh_rows = history_rows(HISTORY / f"{month}.zh-CN.md")

        def pairs(rows: list[list[str]], source: str) -> set[tuple[str, str]]:
            found: set[tuple[str, str]] = set()
            for row in rows:
                date, item_id, item_type, _summary, commit, _details, _pr = row
                if not DATE_RE.fullmatch(date):
                    errors.append(f"{source}: invalid date {date!r}")
                if not ID_RE.fullmatch(item_id):
                    errors.append(f"{source}: invalid id {item_id!r}")
                if item_type not in TYPES:
                    errors.append(f"{source}: invalid type {item_type!r}")
                match = re.search(r"/commit/([0-9a-f]{7,40})", commit)
                if match is None:
                    errors.append(f"{source}: commit link missing a SHA")
                    continue
                found.add((item_id, match.group(1)))
            return found

        en_pairs = pairs(en_rows, f"{month}.md")
        zh_pairs = pairs(zh_rows, f"{month}.zh-CN.md")
        if en_pairs != zh_pairs:
            errors.append(f"{HISTORY / month}: English and Chinese rows do not match")
        for item_id, _sha in en_pairs:
            if item_id in archived:
                errors.append(f"{month}.md: duplicate archived id {item_id!r}")
            archived.add(item_id)
            if item_id in seen:
                errors.append(f"{month}.md: archived id {item_id!r} is still active in docs/work")

    index_check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "render_index.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if index_check.returncode != 0:
        message = index_check.stdout.strip() or index_check.stderr.strip() or "INDEX.md is stale"
        errors.append(message)

    if errors:
        print("\n".join(f"- {error}" for error in errors))
        raise SystemExit(1)
    print(f"docs ok: {len(seen)} work items, {len(archived)} archived")


if __name__ == "__main__":
    main()
