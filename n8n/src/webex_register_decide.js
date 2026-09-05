const base = String($env.N8N_WEBHOOK_URL || '').replace(/\/$/, '');
if (!base) throw new Error('N8N_WEBHOOK_URL not set');
if (!$env.WEBEX_WEBHOOK_SECRET) throw new Error('WEBEX_WEBHOOK_SECRET not set');
const target = `${base}/webhook/webex-transcript`;
const items = ($input.first().json.items || []);
const mine = items.filter(w => w.targetUrl === target && w.resource === 'meetingTranscripts' && w.event === 'created');
if (mine.length) return [{ json: { skip: true, existing: mine.map(w => ({ id: w.id, name: w.name, status: w.status })) } }];
return [{ json: { skip: false, body: { name: 'plady-wiki-webex-transcripts', targetUrl: target, resource: 'meetingTranscripts', event: 'created', secret: $env.WEBEX_WEBHOOK_SECRET, ownedBy: $env.WEBEX_WEBHOOK_OWNED_BY || 'creator' } } }];
