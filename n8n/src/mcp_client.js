// ── shared: llm-wiki MCP client (Streamable HTTP) + Slack notify ─────────────
// Prepended to archive.js / compile.js by n8n/build.py. Runs inside an n8n Code
// node (task runner), so only `this.helpers.httpRequest` and $env are available.
const mcpUrl = $env.LLM_WIKI_MCP_URL;
const bearer = $env.LLM_WIKI_MCP_BEARER_TOKEN;
if (!mcpUrl || !bearer) throw new Error('LLM_WIKI_MCP_URL / LLM_WIKI_MCP_BEARER_TOKEN not set');
let sessionId = null; let rpcId = 0;
const parse = (res) => {
  const ct = String(res.headers['content-type'] || '');
  const text = typeof res.body === 'string' ? res.body : JSON.stringify(res.body);
  if (ct.includes('text/event-stream')) {
    for (const line of text.split('\n')) if (line.startsWith('data:')) { const d = line.slice(5).trim(); if (d) return JSON.parse(d); }
    throw new Error('SSE without data');
  }
  return text.trim() ? JSON.parse(text) : null;
};
const post = async (payload, expectBody = true) => {
  const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', 'Authorization': `Bearer ${bearer}` };
  if (sessionId) headers['Mcp-Session-Id'] = sessionId;
  const res = await this.helpers.httpRequest({ method: 'POST', url: mcpUrl, headers, body: JSON.stringify(payload), returnFullResponse: true, timeout: 120000 });
  const sid = res.headers['mcp-session-id']; if (sid) sessionId = sid;
  if (!expectBody) return null;
  const msg = parse(res);
  if (msg && msg.error) throw new Error(`${payload.method}: ${JSON.stringify(msg.error)}`);
  return msg ? msg.result : null;
};
const call = async (name, args) => {
  const r = await post({ jsonrpc: '2.0', id: ++rpcId, method: 'tools/call', params: { name, arguments: args } });
  const text = (r.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
  if (r.isError) throw new Error(`${name} failed: ${text}`);
  try { return JSON.parse(text); } catch { return { text }; }
};
const mcpInit = async () => {
  await post({ jsonrpc: '2.0', id: ++rpcId, method: 'initialize', params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'n8n-wiki-ingest', version: '2' } } });
  await post({ jsonrpc: '2.0', method: 'notifications/initialized' }, false);
};
const notify = async (msg) => {
  const slack = $env.WIKI_SLACK_WEBHOOK_URL || '';
  if (!slack) return;
  try { await this.helpers.httpRequest({ method: 'POST', url: slack, body: JSON.stringify({ text: msg }), headers: { 'Content-Type': 'application/json' }, timeout: 10000 }); } catch (e) { /* fail-open */ }
};
