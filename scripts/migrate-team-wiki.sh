#!/usr/bin/env bash
set -euo pipefail

SRC="${SRC:-/Users/luna/Desktop_nonsync/teams/100-thieves/team-wiki}"
DST="${DST:-$(pwd)/wiki-workspace}"
APPLY=false

usage() {
  cat <<USAGE
Usage: $0 [options]

Migrate the legacy 100Thieves team-wiki repo into the llm-wiki data workspace.
By default this is a dry-run. Pass --apply to copy files.

Options:
  --src DIR    Legacy team-wiki repository. Default: ${SRC}
  --dst DIR    llm-wiki data workspace. Default: ${DST}
  --apply      Actually copy files and write migration report
  -h, --help   Show this help

Migration layout:
  raw/legacy-team-wiki/raw/          legacy raw notes
  raw/legacy-team-wiki/Clippings/    legacy clippings
  raw/legacy-team-wiki/attachments/  legacy attachments
  raw/legacy-team-wiki/views/        legacy view definitions
  raw/legacy-team-wiki/root/         root-level legacy docs
  wiki/                              existing curated wiki seed pages
  migration/team-wiki-migration-report.md
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --src)
      SRC="$2"
      shift 2
      ;;
    --dst)
      DST="$2"
      shift 2
      ;;
    --apply)
      APPLY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ ! -d "$SRC/.git" ]; then
  echo "Source is not a git repository: ${SRC}" >&2
  exit 1
fi

if [ ! -d "$DST" ]; then
  echo "Destination does not exist: ${DST}" >&2
  exit 1
fi

copy_dir() {
  local from="$1"
  local to="$2"
  if [ ! -d "$from" ]; then
    return 0
  fi

  mkdir -p "$to"
  if [ "$APPLY" = true ]; then
    rsync -a \
      --exclude '.DS_Store' \
      --exclude '.git/' \
      --exclude '.obsidian/' \
      --exclude '.claude/' \
      --exclude '.codex/' \
      --exclude '.tolaria-rename-txn/' \
      "$from/" "$to/"
  else
    rsync -ain \
      --exclude '.DS_Store' \
      --exclude '.git/' \
      --exclude '.obsidian/' \
      --exclude '.claude/' \
      --exclude '.codex/' \
      --exclude '.tolaria-rename-txn/' \
      "$from/" "$to/"
  fi
}


transform_wiki_seed() {
  if [ ! -d "$SRC/wiki" ]; then
    return 0
  fi

  if [ "$APPLY" != true ]; then
    echo "normalize-wiki-seed $SRC/wiki -> $DST/wiki"
    find "$SRC/wiki" -type f -name '*.md' ! -name '.DS_Store' | sed "s#^$SRC/wiki/#  #" | sort | sed -n '1,80p'
    return 0
  fi

  SRC_WIKI="$SRC/wiki" DST_WIKI="$DST/wiki" python3 <<'PY_NORMALIZE'
from pathlib import Path
from datetime import date
import os
import re

src = Path(os.environ['SRC_WIKI'])
dst = Path(os.environ['DST_WIKI'])

def split_frontmatter(text):
    if text.startswith('---\n'):
        end = text.find('\n---\n', 4)
        if end != -1:
            return text[4:end], text[end+5:]
    return '', text

def scalar(frontmatter, key):
    m = re.search(rf'^{re.escape(key)}:\s*(.*)$', frontmatter, re.M)
    if not m:
        return ''
    value = m.group(1).strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value

def first_heading(body):
    for line in body.splitlines():
        if line.startswith('# '):
            return line[2:].strip()
    return ''

def summary_from_body(body):
    m = re.search(r'(?ms)^## Summary\s+(.+?)(?:\n## |\Z)', body)
    if not m:
        return ''
    for line in m.group(1).splitlines():
        line = line.strip()
        if line and not line.startswith('-'):
            return line[:180]
    return ''

def yaml_string(value):
    value = str(value).replace('"', '\\"')
    return f'"{value}"'

for path in src.rglob('*.md'):
    if path.name == '.DS_Store':
        continue
    rel = path.relative_to(src)
    target = dst / rel
    text = path.read_text(encoding='utf-8')
    fm, body = split_frontmatter(text)
    title = scalar(fm, 'title') or first_heading(body) or path.stem
    legacy_type = scalar(fm, 'type') or 'unknown'
    last_updated = scalar(fm, 'updated') or scalar(fm, 'date') or date.today().isoformat()
    purpose = scalar(fm, 'purpose')
    summary = purpose or summary_from_body(body) or f'Legacy team-wiki seed page: {title}'
    rel_posix = rel.as_posix()
    section = rel.parts[0] if len(rel.parts) > 1 else 'root'
    tags = ['legacy-team-wiki', section]
    if legacy_type and legacy_type != 'unknown':
        tags.append(legacy_type.lower())

    new_fm = [
        '---',
        f'title: {yaml_string(title)}',
        'type: doc',
        'status: active',
        f'summary: {yaml_string(summary)}',
        f'last_updated: {yaml_string(last_updated)}',
        'tags:',
    ]
    for tag in tags:
        safe = re.sub(r'[^0-9A-Za-z가-힣_-]+', '-', tag).strip('-').lower() or 'legacy'
        new_fm.append(f'  - {safe}')
    new_fm += [
        f'legacy_source_repo: {yaml_string("100Thieves-team/team-wiki")}',
        f'legacy_source_path: {yaml_string("wiki/" + rel_posix)}',
        f'legacy_type: {yaml_string(legacy_type)}',
        '---',
        '',
    ]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('\n'.join(new_fm) + body.lstrip(), encoding='utf-8')
PY_NORMALIZE
}

count_files() {
  local dir="$1"
  local pattern="$2"
  if [ -d "$dir" ]; then
    find "$dir" -type f -name "$pattern" ! -name '.DS_Store' | wc -l | tr -d ' '
  else
    echo 0
  fi
}

SOURCE_HEAD="$(git -C "$SRC" rev-parse --short HEAD)"
SOURCE_REMOTE="$(git -C "$SRC" remote get-url origin 2>/dev/null || true)"
RAW_MD_COUNT="$(count_files "$SRC/raw" '*.md')"
WIKI_MD_COUNT="$(count_files "$SRC/wiki" '*.md')"
CLIPPING_MD_COUNT="$(count_files "$SRC/Clippings" '*.md')"
ATTACHMENT_COUNT="$(find "$SRC/attachments" -type f 2>/dev/null | grep -v '/.DS_Store$' | wc -l | tr -d ' ' || true)"

cat <<SUMMARY
Source: ${SRC}
Destination: ${DST}
Mode: $([ "$APPLY" = true ] && echo apply || echo dry-run)
Source remote: ${SOURCE_REMOTE}
Source head: ${SOURCE_HEAD}
Legacy raw markdown: ${RAW_MD_COUNT}
Legacy wiki markdown: ${WIKI_MD_COUNT}
Legacy clippings markdown: ${CLIPPING_MD_COUNT}
Legacy attachments: ${ATTACHMENT_COUNT}
SUMMARY

copy_dir "$SRC/raw" "$DST/raw/legacy-team-wiki/raw"
copy_dir "$SRC/Clippings" "$DST/raw/legacy-team-wiki/Clippings"
copy_dir "$SRC/attachments" "$DST/raw/legacy-team-wiki/attachments"
copy_dir "$SRC/views" "$DST/raw/legacy-team-wiki/views"
transform_wiki_seed

ROOT_DEST="$DST/raw/legacy-team-wiki/root"
mkdir -p "$ROOT_DEST"
while IFS= read -r -d '' file; do
  base="$(basename "$file")"
  case "$base" in
    .DS_Store) continue ;;
  esac
  if [ "$APPLY" = true ]; then
    cp -p "$file" "$ROOT_DEST/$base"
  else
    echo "root-file $base -> raw/legacy-team-wiki/root/$base"
  fi
done < <(find "$SRC" -maxdepth 1 -type f \( -name '*.md' -o -name '*.html' -o -name '*.yml' -o -name '*.yaml' \) -print0)

if [ "$APPLY" = true ]; then
  mkdir -p "$DST/migration"
  cat >"$DST/migration/team-wiki-migration-report.md" <<REPORT
---
title: Legacy team-wiki migration report
type: doc
status: active
summary: Migration report for importing 100Thieves-team/team-wiki into llm-wiki data workspace.
last_updated: $(date -u +%Y-%m-%d)
tags: [migration, team-wiki]
---
# Legacy team-wiki migration report

## Source

- Repository: ${SOURCE_REMOTE}
- Local path: ${SRC}
- Commit: ${SOURCE_HEAD}

## Imported layout

| Source | Destination | Notes |
| --- | --- | --- |
| raw/ | raw/legacy-team-wiki/raw/ | Original raw notes preserved |
| Clippings/ | raw/legacy-team-wiki/Clippings/ | Original clippings preserved |
| attachments/ | raw/legacy-team-wiki/attachments/ | Binary/image assets preserved |
| views/ | raw/legacy-team-wiki/views/ | Legacy view definitions preserved |
| root docs | raw/legacy-team-wiki/root/ | Root-level markdown/html docs preserved |
| wiki/ | wiki/ | Curated seed pages normalized to this repo's llm-wiki \`doc\` schema |

## Counts at migration time

- Raw markdown files: ${RAW_MD_COUNT}
- Curated wiki markdown files: ${WIKI_MD_COUNT}
- Clipping markdown files: ${CLIPPING_MD_COUNT}
- Attachments: ${ATTACHMENT_COUNT}

## Follow-up

The legacy repo's own wiki rules are not imported as active rules. Root-level docs such as AGENTS.md/CLAUDE.md are archived under \`raw/legacy-team-wiki/root/\` only.

Run MCP ingest/lint in batches:

1. wiki_ingest path=wiki/people
2. wiki_ingest path=wiki/topics
3. wiki_ingest path=wiki/sources
4. wiki_ingest path=raw/legacy-team-wiki/raw
5. wiki_lint
6. wiki_index_rebuild

REPORT

  echo
  echo "Migration files copied. Destination git status:"
  git -C "$DST" status --short
else
  echo
  echo "Dry-run only. Re-run with --apply to copy files."
fi
