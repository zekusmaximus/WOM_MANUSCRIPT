#!/usr/bin/env python3
"""
Word count utility for manuscript scenes (legacy naming).

Structure:
    manuscript/
      NN-Chapter Title/
        chNN-scMM.md  # scene files with optional YAML front matter

What it reports
 - Scene-by-scene word counts
 - Chapter totals
 - Manuscript total

Notes
 - Only matches legacy scene filenames: chNN-scMM.md
 - Excludes YAML front matter blocks delimited by --- ... --- or ...

Usage
    py -3 scripts/word_count.py --root manuscript [--show-paths]
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Legacy patterns
SCENE_RE = re.compile(r"^ch(?P<ch>\d{2})-sc(?P<sc>\d{2})\.md$", re.IGNORECASE)
CHAPTER_DIR_PATTERNS = [
    re.compile(r"^(?P<ch>\d{2})-"),           # e.g., 01-Chapter One
    re.compile(r"^Chapter-(?P<ch>\d{2})$", re.IGNORECASE),  # tolerate Chapter-01
]

WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


@dataclass
class SceneInfo:
    chapter_num: int
    scene_num: int
    path: Path
    words: int = 0


def strip_yaml_front_matter(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines(True)
    if not lines:
        return text
    first = lines[0].lstrip("\ufeff")
    if first.strip() != "---":
        return text
    end_index = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end_index = i
            break
    if end_index is None:
        return text
    return "".join(lines[end_index + 1 :])


def count_words(text: str) -> int:
    if not text:
        return 0
    body = strip_yaml_front_matter(text)
    return len(WORD_RE.findall(body))


def parse_chapter_dir(dirname: str) -> Optional[int]:
    for pat in CHAPTER_DIR_PATTERNS:
        m = pat.match(dirname)
        if m:
            try:
                return int(m.group("ch"))
            except Exception:
                pass
    m = re.search(r"(\d{2})", dirname)
    return int(m.group(1)) if m else None


def collect_scenes(root: Path) -> List[SceneInfo]:
    scenes: List[SceneInfo] = []
    for chapter_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        ch_num = parse_chapter_dir(chapter_dir.name)
        if ch_num is None:
            continue
        for md in sorted(chapter_dir.glob("*.md")):
            m = SCENE_RE.match(md.name)
            if not m:
                continue
            ch_from_file = int(m.group("ch"))
            sc_num = int(m.group("sc"))
            scenes.append(SceneInfo(chapter_num=ch_from_file, scene_num=sc_num, path=md))
    scenes.sort(key=lambda s: (s.chapter_num, s.scene_num, s.path.name))
    return scenes


def load_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="ignore")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Count words by scene and chapter.")
    ap.add_argument("--root", default="manuscript", help="Root manuscript directory")
    ap.add_argument("--show-paths", action="store_true", help="Show file paths in scene output")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists() or not root.is_dir():
        print(f"Root directory not found: {root}")
        return 2

    scenes = collect_scenes(root)
    if not scenes:
        print("No scenes found (expecting chNN-scMM.md under NN-... folders).")
        return 1

    for s in scenes:
        s.words = count_words(load_text(s.path))

    chapters: Dict[int, List[SceneInfo]] = {}
    for s in scenes:
        chapters.setdefault(s.chapter_num, []).append(s)

    manuscript_total = sum(s.words for s in scenes)

    print("Scene counts:")
    for ch_num in sorted(chapters.keys()):
        for s in chapters[ch_num]:
            line = f"Chapter {s.chapter_num:02d} / Scene {s.scene_num:02d}: {s.words}"
            if args.show_paths:
                line += f"  -  {s.path.as_posix()}"
            print(line)
        ch_total = sum(s.words for s in chapters[ch_num])
        print(f"Chapter {ch_num:02d} total: {ch_total}\n")

    print(f"Manuscript total: {manuscript_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

