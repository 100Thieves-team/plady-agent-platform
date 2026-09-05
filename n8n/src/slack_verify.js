// ── slack front-end: verify the Events API request, answer challenges, and
//    pick out the message that carries a huddle AI-notes canvas ──────────────
// Slack signs every request: X-Slack-Signature = "v0=" + HMAC-SHA256(signing
// secret, "v0:" + X-Slack-Request-Timestamp + ":" + raw body). We verify on the
// raw bytes and reject anything older than 5 minutes (replay).
const crypto = require('crypto');
const item = $input.first();
const secret = $env.SLACK_INGEST_SIGNING_SECRET;
if (!secret) throw new Error('SLACK_INGEST_SIGNING_SECRET is not set on the n8n container');
const raw = await this.helpers.getBinaryDataBuffer(0, 'data');
const h = item.json.headers || {};
const ts = String(h['x-slack-request-timestamp'] || '');
const given = String(h['x-slack-signature'] || '');
if (!/^\d+$/.test(ts) || Math.abs(Date.now() / 1000 - Number(ts)) > 300) throw new Error('Slack request timestamp missing or stale');
const expected = 'v0=' + crypto.createHmac('sha256', secret).update(`v0:${ts}:`).update(raw).digest('hex');
if (given.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected))) {
  throw new Error('X-Slack-Signature mismatch — request rejected');
}
const body = JSON.parse(raw.toString('utf8'));

// Slack verifies the Request URL once with a challenge; echo it back.
if (body.type === 'url_verification') return [{ json: { respond: String(body.challenge || ''), ignore: true, why: 'url_verification' } }];
if (body.type !== 'event_callback' || !body.event) return [{ json: { respond: '', ignore: true, why: 'not an event_callback' } }];

// Huddle AI notes arrive as a canvas file on a message in the channel/thread —
// either on a fresh message or added to the huddle-thread root via
// message_changed. Canvases are file objects with filetype "quip".
const ev = body.event;
const msg = ev.subtype === 'message_changed' ? (ev.message || {}) : ev;
const files = Array.isArray(msg.files) ? msg.files : [];
const canvas = files.find(f => f && (f.filetype === 'quip' || f.mode === 'quip' || f.filetype === 'canvas'));
if (ev.type !== 'message' || !canvas) {
  return [{ json: { respond: '', ignore: true, why: `event ${ev.type}/${ev.subtype || '-'} without a canvas`, event_summary: { type: ev.type, subtype: ev.subtype, files: files.map(f => f && f.filetype) } } }];
}
// Only Slack-generated huddle notes, not any canvas a person shares. Title is
// the signal we have ("Huddle notes ..."/"허들 노트 ..."); keep a manual override
// via the SLACK_INGEST_ANY_CANVAS env for teams that title notes themselves.
const titleOk = /huddle|허들/i.test(String(canvas.title || canvas.name || '')) || (msg.subtype === 'huddle_thread') || $env.SLACK_INGEST_ANY_CANVAS === 'true';
if (!titleOk) return [{ json: { respond: '', ignore: true, why: `canvas "${canvas.title || canvas.name}" is not huddle notes` } }];

return [{ json: {
  respond: '', ignore: false,
  fileId: canvas.id, fileTitle: canvas.title || canvas.name || '',
  channel: ev.channel || msg.channel || '',
  messageTs: msg.ts || ev.ts || '',
  threadTs: msg.thread_ts || '',
  eventTs: ev.event_ts || '',
  team: body.team_id || '',
} }];
