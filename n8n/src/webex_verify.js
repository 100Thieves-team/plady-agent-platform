// Webex signs the raw JSON body with HMAC-SHA1(secret) → X-Spark-Signature.
// Verify against the RAW bytes (never a re-serialised object) with a
// constant-time compare, then hand only the identifiers downstream.
const crypto = require('crypto');
const item = $input.first();
const secret = $env.WEBEX_WEBHOOK_SECRET;
if (!secret) throw new Error('WEBEX_WEBHOOK_SECRET is not set on the n8n container');
const raw = await this.helpers.getBinaryDataBuffer(0, 'data');
const given = String((item.json.headers || {})['x-spark-signature'] || '');
const expected = crypto.createHmac('sha1', secret).update(raw).digest('hex');
if (given.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected))) {
  throw new Error('X-Spark-Signature mismatch — request rejected');
}
const body = JSON.parse(raw.toString('utf8'));
if (body.resource !== 'meetingTranscripts' || body.event !== 'created') {
  return []; // not for us; the webhook already answered 200
}
const d = body.data || {};
if (!d.id || !d.meetingId) throw new Error('webhook payload lacks data.id / data.meetingId');
return [{ json: { transcriptId: d.id, meetingId: d.meetingId, webhookName: body.name || '', createdAt: body.created || '' } }];