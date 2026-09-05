// ── wiki-ingest-raw / step 2: compile knowledge (best effort) ────────────────
// The raw page is committed. Ask Hermes (read-only tools) for a draft, then let
// wiki_apply validate and commit it. On any failure the team is told where the
// raw sits so a person or agent can finish; nothing is lost.
const prev = $input.first().json;
const { rawPath, title, date } = prev;
const hermesUrl = $env.HERMES_API_URL; const hermesKey = $env.HERMES_API_KEY;
try {
  if (!hermesUrl || !hermesKey) throw new Error('HERMES_API_URL / HERMES_API_KEY not set');
  await mcpInit();
  const plan = await call('wiki_ingest_plan', { raw_path: rawPath });
  if ((plan.existing_sources || []).length) {
    return [{ json: { ok: true, rawPath, skipped: 'already compiled', existing_sources: plan.existing_sources } }];
  }
  const rules = await call('wiki_rules', {});
  const rawPage = await call('wiki_content_read', { uri: rawPath });
  const rawText = rawPage.content || rawPage.text || JSON.stringify(rawPage);
  const candidates = (plan.candidates || []).slice(0, 6);
  const existing = [];
  for (const c of candidates) {
    try { const p = await call('wiki_content_read', { uri: c.slug }); existing.push({ slug: c.slug, content: p.content || p.text || '' }); }
    catch (e) { existing.push({ slug: c.slug, error: String(e.message || e) }); }
  }

  const system = `너는 팀 LLM 위키의 ingest 컴파일러다. 아래 규칙(AGENTS.md)을 따른다. 출력은 오직 하나의 \`\`\`json 코드블록이며 그 안은 {"message": string, "changes": [{"path": string, "content": string}]} 형식이다. 설명 문장은 코드블록 밖에 두지 마라.

요구사항:
- changes 에는 (1) wiki/sources/ 아래 새 source 페이지 1개 — frontmatter 에 raw_source_path: "${rawPath}" 를 반드시 포함, (2) 이 회의에서 무언가를 배운 기존 topics/·people/ 페이지의 **전체 새 내용**(수정본) 1개 이상. 후보 페이지의 현재 내용이 아래에 있으니 그것을 바탕으로 고쳐 써라. 바꿀 것이 없는 페이지는 넣지 마라.
- raw 페이지(${rawPath})는 이미 커밋돼 있으니 changes 에 넣지 마라.
- 링크는 [label](topics/t-foo) 또는 [[topics/t-foo]] 형식만. 태그는 소문자-하이픈. 새 페이지 frontmatter 는 title/type/status/summary/last_updated/tags 를 갖춘다 (last_updated: ${date}).
- 회의 내용을 요약해 source 페이지에 담고, topic 페이지에는 결정·변경·새 사실만 반영하며 source 페이지를 가리켜라.
- 비밀값·개인정보(이메일·전화)는 쓰지 마라.`;
  const user = `## 위키 규칙 (wiki_rules)
${typeof rules === 'string' ? rules : (rules.text || rules.rules || JSON.stringify(rules))}

## ingest 계획 (wiki_ingest_plan)
${JSON.stringify({ required: plan.required, candidates, existing_sources: plan.existing_sources, notes: plan.notes }, null, 1)}

## 후보 페이지 현재 내용
${existing.map(e => `### ${e.slug}\n${e.content || ('(읽기 실패: ' + e.error + ')')}`).join('\n\n')}

## 원문 (${rawPath})
${rawText}`;

  const res = await this.helpers.httpRequest({
    method: 'POST', url: `${hermesUrl.replace(/\/$/, '')}/v1/chat/completions`,
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hermesKey}`, 'X-Hermes-Session-Key': `wiki-ingest-${date}-${Math.random().toString(36).slice(2, 8)}` },
    body: JSON.stringify({ model: $env.HERMES_MODEL || 'gpt-5.5', messages: [{ role: 'system', content: system }, { role: 'user', content: user }], stream: false }),
    json: false, timeout: 900000,
  });
  const data = typeof res === 'string' ? JSON.parse(res) : res;
  const text = String(((data.choices || [])[0] || {}).message?.content || '');
  const m = text.match(/```json\s*([\s\S]*?)```/);
  if (!m) throw new Error('Hermes 응답에 json 코드블록이 없음: ' + text.slice(0, 300));
  const draft = JSON.parse(m[1]);
  const changes = (draft.changes || []).filter(c => c && c.path && typeof c.content === 'string' && !c.path.startsWith('raw/'));
  if (!changes.some(c => c.path.startsWith('sources/'))) throw new Error('초안에 sources/ 페이지가 없음');
  // A model that returns a truncated topic page would have wiki_apply commit the
  // deletion faithfully. A rewrite that loses more than 40% of an existing page is
  // not an update we accept unattended — refuse and let a person look.
  for (const ch of changes) {
    const before = existing.find(e => e.slug === ch.path && e.content);
    if (before && ch.content.length < before.content.length * 0.6) {
      throw new Error(`초안이 기존 페이지 ${ch.path} 를 ${before.content.length}→${ch.content.length}자로 줄임 — 자동 반영 거부`);
    }
  }
  const applied = await call('wiki_apply', { mode: 'knowledge', changes, message: draft.message || `ingest(knowledge): ${title} — ${prev.source} ${date}`, expected_head: plan.head });
  return [{ json: { ok: true, rawPath, compiled: changes.map(c => c.path), apply: applied } }];
} catch (e) {
  const reason = String(e.message || e).slice(0, 600);
  await notify(`⚠️ ${prev.source} 회의 자동 ingest — 컴파일 실패. 원문은 보관됨: \`${rawPath}\`\n사유: ${reason}\n→ 에이전트에게 "${rawPath} 를 ingest 해줘" 라고 요청하면 마무리됩니다.`);
  return [{ json: { ok: false, rawPath, error: reason } }];
}
