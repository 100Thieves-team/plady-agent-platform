// ── webex front-end: normalise meeting + transcript into the ingest input ────
const meeting = $('Get meeting').first().json;
const transcript = String($input.first().json.transcript || '').trim();
const ids = $('Verify signature').first().json;
if (!transcript) throw new Error('empty transcript for ' + ids.transcriptId);

const kst = (iso) => new Date(new Date(iso).getTime() + 9 * 3600 * 1000);
const pad = (n) => String(n).padStart(2, '0');
const start = kst(meeting.start || ids.createdAt || Date.now());
const date = `${start.getUTCFullYear()}-${pad(start.getUTCMonth() + 1)}-${pad(start.getUTCDate())}`;
const heldAt = `${date}T${pad(start.getUTCHours())}:${pad(start.getUTCMinutes())}:00+09:00`;
const durationMin = meeting.start && meeting.end ? Math.round((new Date(meeting.end) - new Date(meeting.start)) / 60000) : null;
const title = String(meeting.title || meeting.meetingTopic || `Webex 회의 ${date}`).trim();
const t = title.toLowerCase();
const meetingType = /스크럼|scrum|데일리|daily/.test(t) ? 'daily-scrum' : /멘토|mentor/.test(t) ? 'mentoring' : 'planning';
const slugPart = title.replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').toLowerCase().slice(0, 40) || 'meeting';

return [{ json: {
  rawPath: `raw/meetings/webex-${date}-${slugPart}`,
  title, date, heldAt, meetingType,
  source: 'webex',
  sourceRef: meeting.webLink || '',
  frontmatter: { host: meeting.hostDisplayName || '', duration_min: durationMin, webex_meeting_id: ids.meetingId },
  note: `Webex 자동 녹취록 (${heldAt}). 원문은 수정하지 않는다 — 정정은 wiki/ 페이지에서.`,
  body: transcript,
} }];
