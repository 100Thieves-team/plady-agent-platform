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
copy_dir "$SRC/wiki" "$DST/wiki"

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
| wiki/ | wiki/ | Curated seed pages imported for llm-wiki indexing |

## Counts at migration time

- Raw markdown files: ${RAW_MD_COUNT}
- Curated wiki markdown files: ${WIKI_MD_COUNT}
- Clipping markdown files: ${CLIPPING_MD_COUNT}
- Attachments: ${ATTACHMENT_COUNT}

## Follow-up

Run MCP ingest/lint in batches:

1. wiki_ingest path=people
2. wiki_ingest path=topics
3. wiki_ingest path=sources
4. wiki_ingest path=../raw/legacy-team-wiki/raw
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
