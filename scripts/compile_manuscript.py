#!/usr/bin/env python3
"""
Manuscript compiler for legacy folder/file naming.

Structure (legacy):
    manuscript/
      NN-Chapter Title/
        chNN-scMM.md    # scene files with optional YAML front matter
      header_material.md  # optional; included before chapters

Output:
    output/full_manuscript.md (configurable)

Behavior:
 - Orders chapters by NN from folder name
 - Orders scenes by MM from filename
 - Strips YAML front matter (--- ... --- or --- ... ...)
 - Inserts chapter headings derived from folder name
 - Inserts optional scene separators between scenes
 - Inserts chapter breaks between chapters

Usage examples:
    py -3 scripts/compile_manuscript.py
    py -3 scripts/compile_manuscript.py --output output/manuscript.md --no-header
    py -3 scripts/compile_manuscript.py --scene-sep "***" --chapter-break hr
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Legacy patterns: chapter folder and scene files
CHAPTER_DIR_RE = re.compile(r"^(?P<num>\d{2})-(?P<title>.+)$")
SCENE_FILE_RE = re.compile(r"^ch(?P<ch>\d{2})-sc(?P<sc>\d{2})\.md$", re.IGNORECASE)

# Simple word tokenization for counts
WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


def strip_yaml_front_matter(text: str) -> str:
    """Return text without a leading YAML front matter block.

    This is a non-destructive strip used for scene content.
    """
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


def parse_front_matter(text: str) -> Tuple[Optional[Dict[str, object]], str]:
    """Parse leading YAML front matter into a dict; return (meta, body).

    No external dependencies. Supports a practical subset:
      - key: value scalars
      - key: | or > followed by indented block (captured as a string)
      - simple lists using "- item" under an indented key
    If parsing fails, returns (None, original_text_without_front_matter).
    """
    if not text:
        return None, text
    lines = text.splitlines(True)
    if not lines:
        return None, text
    idx = 0
    # Handle BOM
    lines[0] = lines[0].lstrip("\ufeff")
    if lines[0].strip() != "---":
        return None, text
    # Find end of front matter
    end_index = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end_index = i
            break
    if end_index is None:
        # malformed; do not remove anything
        return None, text
    yaml_lines = [l.rstrip("\n\r") for l in lines[1:end_index]]
    body = "".join(lines[end_index + 1 :])

    def indentation(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    data: Dict[str, object] = {}
    key: Optional[str] = None
    mode: Optional[str] = None  # 'block' or 'list' or None
    base_indent: int = 0
    block_accum: List[str] = []
    list_accum: List[str] = []

    def commit_pending():
        nonlocal key, mode, block_accum, list_accum
        if key is None:
            return
        if mode == 'block':
            data[key] = "\n".join(block_accum).rstrip("\n")
        elif mode == 'list':
            data[key] = list_accum[:]
        key = None
        mode = None
        block_accum = []
        list_accum = []

    i = 0
    while i < len(yaml_lines):
        line = yaml_lines[i]
        if not line.strip():
            # blank line within YAML — treat as paragraph separator for blocks
            if mode == 'block':
                block_accum.append("")
            i += 1
            continue
        ind = indentation(line)
        stripped = line.strip()
        if ':' in stripped and (ind == 0 or key is None):
            # New key
            commit_pending()
            k, v = stripped.split(':', 1)
            key = k.strip()
            v = v.lstrip()
            if v in ('|', '>'):
                mode = 'block'
                base_indent = None  # compute from next non-empty line
                block_accum = []
                i += 1
                # Collect indented block
                while i < len(yaml_lines):
                    ln = yaml_lines[i]
                    if not ln.strip():
                        block_accum.append("")
                        i += 1
                        continue
                    indn = indentation(ln)
                    if base_indent is None:
                        base_indent = indn
                    if indn < (base_indent or 0):
                        break
                    block_accum.append(ln[base_indent:])
                    i += 1
                commit_pending()
                continue
            elif v == '' or v is None:
                # Could be a list or empty scalar; peek next line
                # Default to empty string if nothing follows
                # If next line is indented with '- ', treat as list
                j = i + 1
                saw_list = False
                list_accum = []
                while j < len(yaml_lines):
                    l2 = yaml_lines[j]
                    if not l2.strip():
                        j += 1
                        continue
                    ind2 = indentation(l2)
                    if ind2 <= ind:
                        break
                    s2 = l2.strip()
                    if s2.startswith('- '):
                        saw_list = True
                        list_accum.append(s2[2:].strip())
                        j += 1
                        # collect additional list items
                        while j < len(yaml_lines):
                            l3 = yaml_lines[j]
                            if not l3.strip():
                                j += 1
                                continue
                            ind3 = indentation(l3)
                            if ind3 <= ind:
                                break
                            s3 = l3.strip()
                            if s3.startswith('- '):
                                list_accum.append(s3[2:].strip())
                                j += 1
                            else:
                                break
                        break
                    else:
                        break
                if saw_list:
                    mode = 'list'
                    i = j
                    commit_pending()
                    continue
                else:
                    data[key] = ''
                    key = None
                    mode = None
                    i += 1
                    continue
            else:
                # simple scalar
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                data[key] = v
                key = None
                mode = None
                i += 1
                continue
        else:
            # Indented continuation for current mode (block/list). Already handled in loops above.
            i += 1
            continue

    commit_pending()
    return data or None, body


def count_words(text: str) -> int:
    if not text:
        return 0
    return len(WORD_RE.findall(text))


@dataclass
class Scene:
    chapter_num: int
    scene_num: int
    path: Path


@dataclass
class Chapter:
    number: int
    title: str
    path: Path
    scenes: List[Scene]


def parse_chapter_dir(p: Path) -> Optional[Chapter]:
    if not p.is_dir():
        return None
    m = CHAPTER_DIR_RE.match(p.name)
    if not m:
        return None
    number = int(m.group("num"))
    title = m.group("title").strip()
    return Chapter(number=number, title=title, path=p, scenes=[])


def parse_scene_file(p: Path) -> Optional[Tuple[int, int]]:
    m = SCENE_FILE_RE.match(p.name)
    if not m:
        return None
    return int(m.group("ch")), int(m.group("sc"))


def collect_structure(root: Path) -> List[Chapter]:
    chapters: List[Chapter] = []
    for child in root.iterdir():
        ch = parse_chapter_dir(child)
        if ch is None:
            continue
        # Scenes inside this chapter
        scenes: List[Scene] = []
        for md in child.glob("*.md"):
            parsed = parse_scene_file(md)
            if not parsed:
                continue
            ch_num, sc_num = parsed
            scenes.append(Scene(chapter_num=ch_num, scene_num=sc_num, path=md))
        scenes.sort(key=lambda s: (s.chapter_num, s.scene_num, s.path.name))
        ch.scenes = scenes
        chapters.append(ch)
    chapters.sort(key=lambda c: (c.number, c.title.lower()))
    return chapters


def render_chapter_heading(ch: Chapter, style: str) -> str:
    chapter_label = f"Chapter {ch.number:02d}"
    if style == "none":
        return ""
    if style == "number":
        return f"# {chapter_label}\n\n"
    # default: number+title
    return f"# {chapter_label}: {ch.title}\n\n"


def render_scene_separator(sep: str) -> str:
    if sep == "none":
        return ""
    if sep == "hr":
        return "\n\n<hr class=\"scene-break\" />\n\n"
    if sep == "em":
        return "\n\n***\n\n"
    # custom literal string
    return f"\n\n{sep}\n\n"


def render_chapter_break(style: str) -> str:
    if style == "none":
        return "\n\n"
    if style == "hr":
        return "\n\n<hr class=\"chapter-break\" />\n\n"
    if style == "page":
        # Some tools understand form feed or HTML comment markers
        return "\n\n<!-- CHAPTER BREAK -->\n\n"
    return "\n\n"


def compile_manuscript(
    root: Path,
    output_path: Path,
    include_header: bool = True,
    title_page: bool = True,
    chapter_heading: str = "title",  # title | number | none
    scene_sep: str = "em",           # em | hr | none | <literal>
    chapter_break: str = "hr",      # hr | page | none
) -> int:
    if not root.exists() or not root.is_dir():
        print(f"Root directory not found: {root}")
        return 2

    chapters = collect_structure(root)
    if not chapters:
        print("No chapters found. Ensure legacy folder naming NN-Chapter Title.")
        return 1

    # Build chapter content and compute word count
    chapter_blocks: List[str] = []
    manuscript_words = 0

    for ch in chapters:
        if not ch.scenes:
            continue
        block_parts: List[str] = []
        heading = render_chapter_heading(ch, chapter_heading)
        if heading:
            block_parts.append(heading)
        first_scene = True
        for sc in ch.scenes:
            try:
                text = sc.path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = sc.path.read_text(encoding="utf-8", errors="ignore")
            body = strip_yaml_front_matter(text).strip()
            if not body:
                continue
            if not first_scene:
                block_parts.append(render_scene_separator(scene_sep))
            first_scene = False
            block_parts.append(body + "\n\n")
            manuscript_words += count_words(body)
        if block_parts:
            chapter_blocks.append("".join(block_parts))

    # Compose final document
    parts: List[str] = []

    # Optional title page from header YAML
    header_file = root / "header_material.md"
    header_body: Optional[str] = None
    header_meta: Optional[Dict[str, object]] = None
    if header_file.exists():
        try:
            header_text = header_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            header_text = header_file.read_text(encoding="utf-8", errors="ignore")
        header_meta, header_body = parse_front_matter(header_text)

    if title_page and header_meta:
        parts.append(render_title_page(header_meta, manuscript_words))

    if include_header and header_body:
        hb = header_body.rstrip()
        if hb:
            parts.append(hb + "\n\n")

    # Insert chapters with breaks
    for idx, block in enumerate(chapter_blocks):
        if idx > 0:
            parts.append(render_chapter_break(chapter_break))
        parts.append(block)

    # Ensure output folder exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    compiled = "".join(parts).rstrip() + "\n"
    output_path.write_text(compiled, encoding="utf-8")
    print(f"Wrote: {output_path.as_posix()}")
    return 0


def render_title_page(meta: Dict[str, object], manuscript_words: int) -> str:
    """Render a simple title page from YAML metadata.

    Expected keys (all optional):
      title, subtitle, author, email, phone,
      address (string or list of lines),
      street, city, state, postal_code, country,
      word_count (overrides computed count)
    """
    def get_str(key: str) -> Optional[str]:
        val = meta.get(key)
        if isinstance(val, str):
            s = val.strip()
            return s if s else None
        return None

    def get_list_or_str(key: str) -> List[str]:
        val = meta.get(key)
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, str):
            s = val.strip()
            return [s] if s else []
        return []

    author = get_str('author') or ''
    title = get_str('title') or ''
    subtitle = get_str('subtitle')
    email = get_str('email')
    phone = get_str('phone')

    address_lines: List[str] = []
    address_lines.extend(get_list_or_str('address'))
    # Build from structured fields if provided
    street = get_str('street')
    locality_parts: List[str] = []
    city = get_str('city')
    state = get_str('state')
    postal = get_str('postal_code') or get_str('zip')
    country = get_str('country')
    if street:
        address_lines.append(street)
    if city:
        part = city
        if state:
            part += f", {state}"
        if postal:
            part += f" {postal}"
        address_lines.append(part)
    if country:
        address_lines.append(country)

    # Word count (prefer YAML override)
    wc_yaml = get_str('word_count') or get_str('approx_word_count')
    wc = wc_yaml
    if not wc:
        approx = int(round(manuscript_words / 1000.0)) * 1000
        wc = f"{approx:,}"

    left_block: List[str] = []
    if author:
        left_block.append(author)
    left_block.extend(address_lines)
    if phone:
        left_block.append(phone)
    if email:
        left_block.append(email)
    if wc:
        left_block.append(f"Word Count: {wc}")

    # Title center block
    title_block: List[str] = []
    if title:
        title_block.append(f"# {title}")
    if subtitle:
        title_block.append(f"## {subtitle}")
    if author:
        title_block.append(f"by {author}")

    # Assemble with spacing and a chapter break afterwards
    parts: List[str] = []
    if left_block:
        parts.append("\n".join(left_block).strip() + "\n\n")
    if title_block:
        parts.append("\n".join(title_block).strip() + "\n\n")
    # Add a visual break before manuscript content
    parts.append(render_chapter_break('hr'))
    return "".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Compile manuscript into a single Markdown file.")
    ap.add_argument("--root", default="manuscript", help="Root manuscript directory (default: manuscript)")
    ap.add_argument("--output", default="output/full_manuscript.md", help="Output Markdown file path")
    ap.add_argument("--no-header", action="store_true", help="Do not include header_material.md body content")
    ap.add_argument("--no-title-page", action="store_true", help="Do not generate title page from header YAML")
    ap.add_argument(
        "--chapter-heading",
        choices=["title", "number", "none"],
        default="title",
        help="Chapter heading style (default: title)",
    )
    ap.add_argument(
        "--scene-sep",
        default="em",
        help="Scene separator: em|hr|none|<literal> (default: em=***)",
    )
    ap.add_argument(
        "--chapter-break",
        choices=["hr", "page", "none"],
        default="hr",
        help="Chapter break style between chapters (default: hr)",
    )
    args = ap.parse_args(argv)

    root = Path(args.root)
    output = Path(args.output)
    include_header = not args.no_header
    return compile_manuscript(
        root=root,
        output_path=output,
        include_header=include_header,
        title_page=(not args.no_title_page),
        chapter_heading=args.chapter_heading,
        scene_sep=args.scene_sep,
        chapter_break=args.chapter_break,
    )


if __name__ == "__main__":
    raise SystemExit(main())
