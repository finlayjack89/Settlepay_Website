#!/usr/bin/env node
// Post-deploy smoke probes for the SettlePay edge functions — safe by design:
// nothing is stored, nothing is emailed, no calendar events are created.
//
//   1. OPTIONS preflight on every public function        -> expect 200
//   2. Honeypot POST to enquiry (_gotcha set)            -> expect 200 {ok:true}, stores nothing
//   3. Invalid POST to enquiry (missing fields)          -> expect 400 validation
//   4. GET availability                                  -> expect 200 with days[]
//   5. Junk event to the analytics beacon (not in the    -> expect 204, dropped by allowlist
//      allowlist)
//
// Run after every deploy:  node scripts/smoke-probes.mjs

const BASE = 'https://xqpbcoldcqfxfwhcqlcy.supabase.co/functions/v1';
let failures = 0;

const check = (label, ok, detail = '') => {
  console.log(`${ok ? '  ok ' : 'FAIL '} ${label}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures += 1;
};

for (const fn of ['enquiry', 'availability', 'book', 'booking-manage', 'events', 'brand-preview']) {
  const res = await fetch(`${BASE}/${fn}`, { method: 'OPTIONS' }).catch(() => null);
  check(`OPTIONS ${fn}`, !!res && res.status === 200, `status ${res?.status}`);
}

{
  const fd = new FormData();
  fd.set('_gotcha', 'smoke-probe');
  const res = await fetch(`${BASE}/enquiry`, { method: 'POST', body: fd }).catch(() => null);
  const body = res ? await res.json().catch(() => null) : null;
  check('enquiry honeypot (silent ok, stores nothing)', !!res && res.status === 200 && body?.ok === true, `status ${res?.status}`);
}

{
  const fd = new FormData();
  fd.set('name', 'Smoke Probe');
  const res = await fetch(`${BASE}/enquiry`, { method: 'POST', body: fd }).catch(() => null);
  check('enquiry invalid POST rejected', !!res && res.status === 400, `status ${res?.status}`);
}

{
  const res = await fetch(`${BASE}/availability`).catch(() => null);
  const body = res ? await res.json().catch(() => null) : null;
  check('availability returns days[]', !!res && res.status === 200 && Array.isArray(body?.days), `days ${body?.days?.length}`);
}

{
  const res = await fetch(`${BASE}/events`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ event: 'smoke_probe_not_allowlisted' }),
  }).catch(() => null);
  check('events drops junk (allowlist)', !!res && res.status === 204, `status ${res?.status}`);
}

console.log(failures ? `\n${failures} probe(s) FAILED` : '\nAll probes passed');
process.exit(failures ? 1 : 0);
