// ── slack front-end: fetch the notes canvas and normalise into the ingest input
const it = $input.first().json;
const token = $env.SLACK_INGEST_BOT_TOKEN;
if (!token) throw new Error('SLACK_INGEST_BOT_TOKEN is not set on the n8n container');
const api = ($env.SLACK_API_BASE || 'https://slack.com/api').replace(/\/$/, '');
const slack = async (method, params) => {
  const res = await this.helpers.httpRequest({ method: 'GET', url: `${api}/${method}`, qs: params, headers: { Authorization: `Bearer ${token}` }, json: true, timeout: 30000 });
  if (!res || res.ok !== true) throw new Error(`${method}: ${res && res.error ? res.error : 'unexpected response'}`);
  return res;
};

const info = await slack('files.info', { file: it.fileId });
const file = info.file || {};
if (file.is_huddle_canvas === false && $env.SLACK_INGEST_ANY_CANVAS !== 'true') {
  throw new Error(`canvas ${it.fileId} is not a huddle notes canvas (is_huddle_canvas=false)`);
}
let channelName = it.channel;
try { const ci = await slack('conversations.info', { channel: it.channel }); channelName = (ci.channel && ci.channel.name) || it.channel; } catch (e) { /* keep id */ }
let permalink = file.permalink || '';
if (!permalink && it.messageTs) { try { const pl = await slack('chat.getPermalink', { channel: it.channel, message_ts: it.messageTs }); permalink = pl.permalink || ''; } catch (e) { /* optional */ } }

// Canvas text: Slack serves the canvas document at url_private(_download);
// depending on the workspace it is HTML or Markdown-ish text. Strip HTML if
// present; fall back to files.info's own preview/content fields.
let body = '';
const dl = file.url_private_download || file.url_private;
if (dl) {
  try {
    const res = await this.helpers.httpRequest({ method: 'GET', url: dl, headers: { Authorization: `Bearer ${token}` }, returnFullResponse: true, encoding: 'text', timeout: 60000 });
    const ct = String(res.headers['content-type'] || '');
    let text = typeof res.body === 'string' ? res.body : JSON.stringify(res.body);
    if (/html/i.test(ct) || /^\s*<(!doctype|html)/i.test(text)) {
      text = text.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, '')
        .replace(/<\/(p|div|li|h[1-6]|tr|br)>/gi, '\n').replace(/<li[^>]*>/gi, '- ').replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/\n{3,}/g, '\n\n').trim();
    }
    body = text.trim();
  } catch (e) { body = ''; }
}
if (!body) body = String(file.plain_text || file.preview || file.content || '').trim();
if (!body) throw new Error(`canvas ${it.fileId} has no readable content (files.info fields: ${Object.keys(file).join(',')})`);

// Slack keeps the full huddle transcript as a separate file the canvas points
// at (files.info.huddle_transcript_file_id). Append it when readable — the
// canvas is Slack AI's summary; the transcript is the evidence.
let transcript = '';
const trId = file.huddle_transcript_file_id;
if (trId && trId !== it.fileId) {
  try {
    const ti = await slack('files.info', { file: trId });
    const tf = ti.file || {};
    const tdl = tf.url_private_download || tf.url_private;
    if (tdl) {
      const tres = await this.helpers.httpRequest({ method: 'GET', url: tdl, headers: { Authorization: `Bearer ${token}` }, returnFullResponse: true, encoding: 'text', timeout: 120000 });
      let ttext = typeof tres.body === 'string' ? tres.body : JSON.stringify(tres.body);
      const tct = String(tres.headers['content-type'] || '');
      if (/json/i.test(tct) || /^\s*[\[{]/.test(ttext)) {
        // JSON transcripts: keep speaker + text lines if the shape is recognisable, else raw.
        try {
          const j = JSON.parse(ttext);
          const items = Array.isArray(j) ? j : (j.segments || j.transcript || j.items || j.lines || []);
          const lines = items.map(x => x && typeof x === 'object' ? `${x.speaker || x.user || x.user_name || x.name || ''}${(x.speaker || x.user || x.user_name || x.name) ? ': ' : ''}${x.text || x.content || x.transcript || ''}`.trim() : String(x)).filter(Boolean);
          ttext = lines.length ? lines.join('\n') : ttext;
        } catch (e) { /* keep raw */ }
      } else if (/html/i.test(tct) || /^\s*<(!doctype|html|div)/i.test(ttext)) {
        ttext = ttext.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/\s{2,}/g, ' ').trim();
      }
      transcript = ttext.trim();
    }
  } catch (e) { transcript = ''; }
}
if (transcript) body = `${body}\n\n## Transcript\n\n${transcript}`;

const kst = (sec) => new Date(Number(sec) * 1000 + 9 * 3600 * 1000);
const pad = (n) => String(n).padStart(2, '0');
const when = kst(it.messageTs || file.created || Date.now() / 1000);
const date = `${when.getUTCFullYear()}-${pad(when.getUTCMonth() + 1)}-${pad(when.getUTCDate())}`;
const heldAt = `${date}T${pad(when.getUTCHours())}:${pad(when.getUTCMinutes())}:00+09:00`;
const title = String(it.fileTitle || `#${channelName} 허들 ${date}`).trim();
const t = `${title} ${channelName}`.toLowerCase();
const meetingType = /스크럼|scrum|데일리|daily|standup/.test(t) ? 'daily-scrum' : /멘토|mentor/.test(t) ? 'mentoring' : 'planning';
const chanSlug = String(channelName).replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').toLowerCase().slice(0, 30) || 'channel';

return [{ json: {
  rawPath: `raw/meetings/slack-huddle-${date}-${chanSlug}-${String(it.fileId).slice(-6).toLowerCase()}`,
  title, date, heldAt, meetingType,
  source: 'slack-huddle',
  sourceRef: permalink,
  frontmatter: { slack_channel: `#${channelName}`, slack_canvas_id: it.fileId, slack_transcript_file_id: trId || '' },
  note: `Slack AI 허들 노트 (#${channelName}, ${heldAt}). Slack 이 생성한 요약·transcript 를 그대로 보관한다 — 정정은 wiki/ 페이지에서.`,
  body,
} }];
