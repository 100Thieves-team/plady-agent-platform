// ── wiki-ingest-raw / step 1: preserve the original ──────────────────────────
// Input (from the calling workflow, one item):
//   rawPath   raw/meetings/<source>-<date>-<slug>      (slug already built)
//   title, date (YYYY-MM-DD), heldAt (ISO+09:00), meetingType, source, sourceRef
//   frontmatter  optional extra scalar fields for the page header
//   body      the transcript / notes text
// Deterministic and must succeed; compilation is best-effort afterwards.
const it = $input.first().json;
for (const k of ['rawPath', 'title', 'date', 'body', 'source']) if (!it[k]) throw new Error(`ingest input lacks ${k}`);
if (!/^raw\//.test(it.rawPath)) throw new Error(`rawPath must live under raw/: ${it.rawPath}`);
const q = (s) => JSON.stringify(String(s));
const extra = Object.entries(it.frontmatter || {}).filter(([, v]) => v !== null && v !== undefined && v !== '')
  .map(([k, v]) => `${k}: ${typeof v === 'number' ? v : q(v)}`);
const fm = [
  '---',
  `title: ${q(it.title)}`,
  'type: raw',
  'source_type: meetings',
  `date: ${it.date}`,
  it.heldAt ? `held_at: ${q(it.heldAt)}` : null,
  `meeting_type: ${it.meetingType || 'planning'}`,
  `source: ${it.source}`,
  it.sourceRef ? `source_ref: ${q(it.sourceRef)}` : null,
  ...extra,
  `managed_by: n8n-${it.source}-ingest`,
  '---',
].filter(Boolean).join('\n');
const intro = it.note || `${it.source} 자동 수집 원문 (${it.heldAt || it.date}). 원문은 수정하지 않는다 — 정정은 wiki/ 페이지에서.`;
const content = `${fm}\n\n# ${it.title}\n\n> ${intro}\n\n${String(it.body).trim()}\n`;

await mcpInit();
// Redelivery and reruns are normal (Webex resends, Slack edits the same
// message several times): an already-preserved original is success, and
// preserved sources are create-only anyway.
let archive; let alreadyArchived = false;
try { await call('wiki_content_read', { uri: it.rawPath }); alreadyArchived = true; archive = { skipped: 'already archived' }; } catch (e) { /* not there yet */ }
if (!alreadyArchived) {
  archive = await call('wiki_apply', { mode: 'archive', changes: [{ path: it.rawPath, content }], message: `archive(${it.source}): ${it.title} ${it.date}` });
}
return [{ json: { ...it, body: undefined, bodyChars: String(it.body).length, alreadyArchived, archive } }];
