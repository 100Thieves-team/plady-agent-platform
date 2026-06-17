#!/usr/bin/env python3
"""Normalize legacy Tolaria/Obsidian markdown for the Hugo raw UI.

Default is dry-run. Use --apply to write changes.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
INLINE_TAGS_RE = re.compile(r"^(\s*tags:\s*)\[([^\]]*)\](\s*)$")
DROP_TAGS = {"tolaria", "legacy-team-wiki"}


@dataclass
class Change:
    path: Path
    wikilinks: int = 0
    mapped_links: int = 0
    plain_links: int = 0
    tag_lines: int = 0


def frontmatter_parts(text: str) -> tuple[str, str, str]:
    if not text.startswith("---\n"):
        return "", "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", "", text
    fm = text[4:end]
    body = text[end + len("\n---") :]
    if body.startswith("\n"):
        body = body[1:]
    return "---\n", fm, body


def extract_frontmatter_value(fm: str, key: str) -> str | None:
    m = re.search(rf"^\s*{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", fm, re.M)
    return m.group(1).strip() if m else None


def build_wiki_link_map(wiki_root: Path) -> dict[str, str]:
    links: dict[str, str] = {}
    if not wiki_root.exists():
        return links
    for path in wiki_root.rglob("*.md"):
        rel = path.relative_to(wiki_root)
        if len(rel.parts) < 2:
            continue
        section = rel.parts[0]
        if section not in {"people", "sources", "topics"}:
            continue
        stem = path.stem
        href = f"/{section}/{quote(stem)}/"
        links.setdefault(stem, href)
        text = path.read_text(encoding="utf-8")
        _, fm, _ = frontmatter_parts(text)
        title = extract_frontmatter_value(fm, "title")
        if title:
            links.setdefault(title, href)
    return links


def normalize_inline_tags(line: str) -> tuple[str, bool]:
    m = INLINE_TAGS_RE.match(line)
    if not m:
        return line, False
    prefix, raw_tags, suffix = m.groups()
    seen: set[str] = set()
    tags: list[str] = []
    for raw in raw_tags.split(","):
        tag = raw.strip().strip("'\"")
        if not tag or tag in DROP_TAGS or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return f"{prefix}[{', '.join(tags)}]{suffix}", True


def normalize_block_tags(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    changed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if not re.match(r"^\s*tags:\s*$", line):
            new_line, did = normalize_inline_tags(line)
            out.append(new_line)
            changed += int(did and new_line != line)
            i += 1
            continue

        out.append(line)
        i += 1
        seen: set[str] = set()
        block: list[str] = []
        block_changed = False
        while i < len(lines) and re.match(r"^\s*-\s+", lines[i]):
            tag = re.sub(r"^\s*-\s+", "", lines[i]).strip().strip("'\"")
            if tag in DROP_TAGS or tag in seen:
                block_changed = True
            else:
                seen.add(tag)
                block.append(lines[i])
            i += 1
        out.extend(block)
        changed += int(block_changed)
    return out, changed


def replace_wikilinks(text: str, links: dict[str, str], in_frontmatter: bool, change: Change) -> str:
    def repl(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        change.wikilinks += 1
        if in_frontmatter:
            change.plain_links += 1
            return label
        href = links.get(target) or links.get(label)
        if href:
            change.mapped_links += 1
            return f"[{label}]({href})"
        change.plain_links += 1
        return label

    return WIKILINK_RE.sub(repl, text)


def normalize_file(path: Path, links: dict[str, str]) -> tuple[str, Change | None]:
    original = path.read_text(encoding="utf-8")
    prefix, fm, body = frontmatter_parts(original)
    change = Change(path=path)

    if prefix:
        fm = replace_wikilinks(fm, links, True, change)
        fm_lines, tag_changes = normalize_block_tags(fm.splitlines())
        change.tag_lines += tag_changes
        fm = "\n".join(fm_lines)
        if fm and not fm.endswith("\n"):
            fm += "\n"
        body = replace_wikilinks(body, links, False, change)
        updated = f"---\n{fm}---\n{body}"
    else:
        updated = replace_wikilinks(original, links, False, change)

    return updated, change if updated != original else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize legacy raw markdown links/tags for Hugo UI")
    parser.add_argument("--workspace", default="wiki-workspace", help="wiki data repo path")
    parser.add_argument("--root", default="raw/legacy-team-wiki", help="path inside workspace to normalize")
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    parser.add_argument("--limit", type=int, default=30, help="max changed files to print")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    root = workspace / args.root
    links = build_wiki_link_map(workspace / "wiki")
    changes: list[Change] = []

    for path in sorted(root.rglob("*.md")):
        updated, change = normalize_file(path, links)
        if not change:
            continue
        changes.append(change)
        if args.apply:
            path.write_text(updated, encoding="utf-8")

    print("mode=apply" if args.apply else "mode=dry-run")
    print(f"wiki_link_targets={len(links)}")
    print(f"changed_files={len(changes)}")
    print(f"wikilinks={sum(c.wikilinks for c in changes)}")
    print(f"mapped_markdown_links={sum(c.mapped_links for c in changes)}")
    print(f"plain_text_links={sum(c.plain_links for c in changes)}")
    print(f"tag_blocks_or_lines_changed={sum(c.tag_lines for c in changes)}")
    for change in changes[: args.limit]:
        print(
            f"- {change.path.relative_to(workspace)} "
            f"wikilinks={change.wikilinks} mapped={change.mapped_links} plain={change.plain_links} tags={change.tag_lines}"
        )
    if len(changes) > args.limit:
        print(f"... {len(changes) - args.limit} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
