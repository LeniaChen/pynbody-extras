#!/usr/bin/env python3
"""Create a new bilingual work item under ``docs/work``."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "docs" / "work"
HISTORY = ROOT / "docs" / "history"
TEMPLATE = WORK / "_template"
PREFIX = {
    "requirement": "REQ",
    "feature": "FEAT",
    "bug": "BUG",
    "task": "TASK",
    "spike": "SPIKE",
}
ID_RE = re.compile(r"\b(?:REQ|FEAT|BUG|TASK|SPIKE)-\d{4}\b")


def managed_ids() -> set[str]:
    """IDs already used by active or archived work items."""
    ids: set[str] = set()
    for meta_path in WORK.glob("*/meta.json"):
        if meta_path.parent.name.startswith("_"):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        item_id = str(meta.get("id", ""))
        if ID_RE.fullmatch(item_id):
            ids.add(item_id)
    for pattern in ("[0-9][0-9][0-9][0-9]-[0-9][0-9].md", "[0-9][0-9][0-9][0-9]-[0-9][0-9].zh-CN.md"):
        for path in HISTORY.glob(pattern):
            ids.update(match.group(0) for match in ID_RE.finditer(path.read_text(encoding="utf-8")))
    return ids


def next_id(kind: str) -> str:
    prefix = PREFIX[kind]
    numbers = [int(item.split("-")[1]) for item in managed_ids() if item.startswith(f"{prefix}-")]
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, choices=sorted(PREFIX))
    parser.add_argument("--title-en", required=True)
    parser.add_argument("--title-zh", required=True)
    args = parser.parse_args()

    item_id = next_id(args.type)
    target = WORK / item_id
    if target.exists():
        raise SystemExit(f"{target} already exists")

    shutil.copytree(TEMPLATE, target)
    today = date.today().isoformat()

    meta_path = target / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "id": item_id,
            "type": args.type,
            "status": "draft",
            "title_en": args.title_en,
            "title_zh": args.title_zh,
            "created": today,
            "updated": today,
        }
    )
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    replacements = {
        "{{ID}}": item_id,
        "{{TITLE_EN}}": args.title_en,
        "{{TITLE_ZH}}": args.title_zh,
        "{{DATE}}": today,
    }
    for path in target.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        for needle, value in replacements.items():
            text = text.replace(needle, value)
        path.write_text(text, encoding="utf-8")

    print(target)


if __name__ == "__main__":
    main()
