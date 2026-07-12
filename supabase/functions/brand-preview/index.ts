// `brand-preview` Edge Function — powers the /preview/ "see your payment page" tool.
//
// Takes a visitor's website URL, reads their public brand via Brandfetch (logo,
// brand colour, display font, name) and drafts short, compliance-bounded
// microcopy via Claude Haiku. Returns a JSON brand profile the front-end pours
// into the mockup checkout. The front-end falls back to manual entry on any
// error, so this endpoint must always return a clean JSON envelope — never hang.
//
// Public endpoint: deploy with `--no-verify-jwt` (the anonymous form POST carries
// no Supabase auth header), exactly like the `enquiry` function.
//
// Env (set as function secrets — see .env.example):
//   BRANDFETCH_API_KEY   Brandfetch Brand API key (required for live previews)
//   ANTHROPIC_API_KEY    Anthropic API key for microcopy (optional; omit = deterministic copy)
//   ALLOWED_ORIGIN       CORS origin (default "*"; set to https://settlepay.uk in prod)
//   RATE_LIMIT_PER_MIN   max requests per IP per minute (default 10)
//   CACHE_TTL_HOURS      brand-profile cache lifetime in hours (default 168 = 7 days)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically and used
// only for best-effort caching + rate-limiting; if the tables are absent the
// function still works (cache/limit simply skipped).

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';
const RATE_LIMIT_PER_MIN = Number(Deno.env.get('RATE_LIMIT_PER_MIN') ?? '10');
const CACHE_TTL_HOURS = Number(Deno.env.get('CACHE_TTL_HOURS') ?? '168');

// Anthropic API version header (request version, NOT a model id — keep as-is).
const ANTHROPIC_VERSION = '2023-06-01';
const HAIKU_MODEL = 'claude-haiku-4-5';

// Microcopy provider selection for the A/B test:
//   COPY_PROVIDER = 'anthropic' (default) | 'openai' | 'both'
// In 'both' mode the function calls BOTH providers and returns each variant in
// `copyAB` for side-by-side comparison (and bypasses the cache so every call is
// live). OPENAI_COPY_MODEL is a verified id from the account's /v1/models list.
const COPY_PROVIDER = (Deno.env.get('COPY_PROVIDER') ?? 'anthropic').toLowerCase();
const OPENAI_COPY_MODEL = Deno.env.get('OPENAI_COPY_MODEL') ?? 'gpt-5.6-luna';

const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, 'content-type': 'application/json' },
  });
}

type Copy = { headline: string; subcopy: string };

interface BrandProfile {
  name: string;
  domain: string;
  logoUrl: string | null;
  colors: { primary: string; onPrimary: string } | null;
  font: string | null;
  copy: Copy | null;
  // Present only in COPY_PROVIDER='both' mode — both variants for A/B comparison.
  copyAB?: { anthropic: Copy | null; openai: Copy | null; models: { anthropic: string; openai: string } };
  source: string;
}

// ---- helpers ---------------------------------------------------------------

/** Strip to a registrable host (drop scheme, path, leading www). */
function toDomain(raw: string): string | null {
  let v = String(raw || '').trim();
  if (!v) return null;
  if (!/^https?:\/\//i.test(v)) v = 'https://' + v;
  try {
    const u = new URL(v);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    const host = u.hostname.replace(/^www\./i, '').toLowerCase();
    if (!host.includes('.')) return null;
    return host;
  } catch {
    return null;
  }
}

/** WCAG-ish: ink or paper that reads on top of a brand hex (mirrors readable()). */
function onColour(hex: string): string {
  const c = hex.replace('#', '');
  if (c.length !== 6) return '#ffffff';
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.42 ? '#0f172a' : '#ffffff';
}

function relLum(hex: string): number {
  const c = hex.replace('#', '');
  if (c.length !== 6) return 0.5;
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

const isHex = (s: unknown): s is string => typeof s === 'string' && /^#[0-9a-fA-F]{6}$/.test(s);

/** Choose a brand colour: accent first, then brand, then the most "branded"
 *  (mid-luminance, not near-white/near-black) of whatever's offered. */
function pickColour(colors: any[]): string | null {
  const valid = (colors || []).filter((c) => isHex(c?.hex));
  if (!valid.length) return null;
  const byType = (t: string) => valid.find((c) => String(c.type).toLowerCase() === t);
  const accent = byType('accent') || byType('brand');
  if (accent) return accent.hex;
  // Otherwise prefer a colour with real presence (avoid near-white/near-black).
  const mid = valid
    .map((c) => ({ hex: c.hex, l: relLum(c.hex) }))
    .filter((c) => c.l > 0.05 && c.l < 0.85)
    .sort((a, b) => Math.abs(0.4 - a.l) - Math.abs(0.4 - b.l));
  return (mid[0] || valid[0]).hex;
}

/** Choose a logo: a full logo on a light background reads best on the white
 *  checkout; fall back to symbol/icon, then anything with a usable raster/svg. */
function pickLogo(logos: any[]): string | null {
  const all = (logos || []).filter((l) => Array.isArray(l?.formats) && l.formats.length);
  if (!all.length) return null;
  const fmtSrc = (l: any) => {
    const f =
      l.formats.find((x: any) => x.format === 'svg') ||
      l.formats.find((x: any) => x.format === 'png') ||
      l.formats[0];
    return f?.src || null;
  };
  const order = (l: any) => {
    const type = String(l.type).toLowerCase();
    const theme = String(l.theme).toLowerCase();
    let score = 0;
    if (type === 'logo') score += 4;
    else if (type === 'symbol' || type === 'icon') score += 2;
    if (theme === 'light' || theme === '') score += 1; // light/neutral suits white bg
    return score;
  };
  const best = [...all].sort((a, b) => order(b) - order(a))[0];
  return fmtSrc(best);
}

function pickFont(fonts: any[]): string | null {
  const valid = (fonts || []).filter((f) => typeof f?.name === 'string' && f.name.trim());
  if (!valid.length) return null;
  const title = valid.find((f) => String(f.type).toLowerCase() === 'title');
  return (title || valid[0]).name.trim();
}

async function hashIp(ip: string): Promise<string> {
  const data = new TextEncoder().encode('sp-bp:' + ip);
  const buf = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

// ---- Brandfetch ------------------------------------------------------------

async function fetchBrand(domain: string, key: string) {
  const res = await fetch('https://api.brandfetch.io/v2/brands/' + encodeURIComponent(domain), {
    headers: { Authorization: 'Bearer ' + key, accept: 'application/json' },
  });
  if (res.status === 404) return { notFound: true as const };
  if (!res.ok) {
    console.error('brandfetch error', res.status, await res.text().catch(() => ''));
    return { error: true as const, status: res.status };
  }
  return { data: await res.json() };
}

// ---- Claude microcopy (compliance-bounded) ---------------------------------

const COPY_SYSTEM = [
  'You write one short headline and one short reassurance line for an ILLUSTRATIVE',
  'mock payment page used by SettlePay, a UK developer of bespoke branded checkouts.',
  'Voice: UK English, plain, confident, no hype. Title Case headline of at most 8 words.',
  'Subcopy: one calm sentence, at most 18 words, about paying this business securely on a',
  'page that looks like them.',
  'HARD RULES — never break: do NOT claim the business or SettlePay is "FCA authorised",',
  '"FCA regulated", "PCI compliant" or "PCI DSS compliant"; do NOT invent statistics,',
  'testimonials, prices, awards or client relationships; no emoji; no exclamation marks.',
  'Return ONLY minified JSON: {"headline":"...","subcopy":"..."} and nothing else.',
].join(' ');

function copyPrompt(name: string, context: string): string {
  return (
    'Business name: ' + name + '\n' +
    'What they do (may be empty): ' + (context || 'unknown') + '\n' +
    'Write the headline and subcopy JSON.'
  );
}

function parseCopy(text: string): Copy | null {
  const match = String(text || '').match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    const headline = String(parsed.headline || '').trim();
    const subcopy = String(parsed.subcopy || '').trim();
    if (!headline && !subcopy) return null;
    return { headline, subcopy };
  } catch {
    return null;
  }
}

async function draftCopyAnthropic(name: string, context: string, key: string): Promise<Copy | null> {
  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': key,
        'anthropic-version': ANTHROPIC_VERSION,
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: HAIKU_MODEL,
        max_tokens: 200,
        system: COPY_SYSTEM,
        messages: [{ role: 'user', content: copyPrompt(name, context) }],
      }),
    });
    if (!res.ok) {
      console.error('anthropic error', res.status, await res.text().catch(() => ''));
      return null;
    }
    const body = await res.json();
    // Cost tracking: log token usage so spend can be attributed to this feature.
    if (body?.usage) {
      console.log('brand-preview anthropic usage', JSON.stringify({ model: HAIKU_MODEL, ...body.usage }));
    }
    const text: string = (body?.content || [])
      .filter((b: any) => b.type === 'text')
      .map((b: any) => b.text)
      .join('');
    return parseCopy(text);
  } catch (e) {
    console.error('draftCopyAnthropic failed', e);
    return null;
  }
}

// OpenAI microcopy (GPT-5.6 Luna by default). The model id is verified against
// the account's /v1/models list. Chat Completions with `max_completion_tokens`
// (the newer models reject `max_tokens`), low reasoning effort, and JSON mode.
// NOTE: coded but NOT verified end-to-end at wiring time — the OpenAI account
// returned `insufficient_quota`. Run one live call after adding billing to
// confirm the request shape before trusting the A/B numbers.
async function draftCopyOpenAI(name: string, context: string, key: string, model: string): Promise<Copy | null> {
  try {
    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + key, 'content-type': 'application/json' },
      body: JSON.stringify({
        model,
        max_completion_tokens: 800,
        reasoning_effort: 'low',
        response_format: { type: 'json_object' },
        messages: [
          { role: 'system', content: COPY_SYSTEM },
          { role: 'user', content: copyPrompt(name, context) },
        ],
      }),
    });
    if (!res.ok) {
      console.error('openai error', res.status, await res.text().catch(() => ''));
      return null;
    }
    const body = await res.json();
    if (body?.usage) {
      console.log('brand-preview openai usage', JSON.stringify({ model, ...body.usage }));
    }
    const text: string = body?.choices?.[0]?.message?.content ?? '';
    return parseCopy(text);
  } catch (e) {
    console.error('draftCopyOpenAI failed', e);
    return null;
  }
}

// Honours COPY_PROVIDER. In 'both' mode runs the two providers in parallel and
// returns each variant in copyAB for A/B comparison; the live `copy` stays
// Anthropic-primary so the preview UI is deterministic while you evaluate.
async function generateCopy(
  name: string,
  context: string,
): Promise<{ copy: Copy | null; copyAB?: BrandProfile['copyAB'] }> {
  const anthropicKey = Deno.env.get('ANTHROPIC_API_KEY');
  const openaiKey = Deno.env.get('OPENAI_API_KEY');
  const wantA = COPY_PROVIDER === 'anthropic' || COPY_PROVIDER === 'both';
  const wantO = COPY_PROVIDER === 'openai' || COPY_PROVIDER === 'both';

  const [a, o] = await Promise.all([
    wantA && anthropicKey ? draftCopyAnthropic(name, context, anthropicKey) : Promise.resolve(null),
    wantO && openaiKey ? draftCopyOpenAI(name, context, openaiKey, OPENAI_COPY_MODEL) : Promise.resolve(null),
  ]);

  if (COPY_PROVIDER === 'both') {
    return {
      copy: a ?? o,
      copyAB: { anthropic: a, openai: o, models: { anthropic: HAIKU_MODEL, openai: OPENAI_COPY_MODEL } },
    };
  }
  return { copy: COPY_PROVIDER === 'openai' ? o : a };
}

// ---- handler ---------------------------------------------------------------

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  let payload: { url?: string };
  try {
    payload = await req.json();
  } catch {
    return json({ error: 'invalid-json' }, 400);
  }

  const domain = toDomain(payload.url || '');
  if (!domain) return json({ error: 'invalid-url' }, 400);

  const brandKey = Deno.env.get('BRANDFETCH_API_KEY');
  if (!brandKey) {
    console.warn('BRANDFETCH_API_KEY not set — live previews disabled.');
    return json({ error: 'not-configured' }, 503);
  }

  // Best-effort Supabase client for cache + rate-limit. Any failure is non-fatal.
  let supabase: ReturnType<typeof createClient> | null = null;
  try {
    const sbUrl = Deno.env.get('SUPABASE_URL');
    const sbKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
    if (sbUrl && sbKey) supabase = createClient(sbUrl, sbKey);
  } catch (_) {
    supabase = null;
  }

  // Rate-limit by IP (best-effort).
  const ip = (req.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'unknown';
  if (supabase && RATE_LIMIT_PER_MIN > 0) {
    try {
      const ipHash = await hashIp(ip);
      const since = new Date(Date.now() - 60_000).toISOString();
      const { count } = await supabase
        .from('brand_preview_requests')
        .select('id', { count: 'exact', head: true })
        .eq('ip_hash', ipHash)
        .gte('created_at', since);
      if ((count ?? 0) >= RATE_LIMIT_PER_MIN) {
        return json({ error: 'rate-limited' }, 429);
      }
      await supabase.from('brand_preview_requests').insert({ ip_hash: ipHash, domain });
    } catch (_) {
      /* table missing or transient — skip the limiter */
    }
  }

  // In A/B ('both') mode, bypass the cache so every call runs both providers live.
  const useCache = COPY_PROVIDER !== 'both';

  // Cache lookup (best-effort).
  if (supabase && useCache) {
    try {
      const { data: cached } = await supabase
        .from('brand_previews')
        .select('profile, fetched_at')
        .eq('domain', domain)
        .maybeSingle();
      if (cached?.profile && cached.fetched_at) {
        const ageMs = Date.now() - new Date(cached.fetched_at).getTime();
        if (ageMs < CACHE_TTL_HOURS * 3_600_000) {
          return json(cached.profile);
        }
      }
    } catch (_) {
      /* cache miss path */
    }
  }

  // Extract brand.
  const brand = await fetchBrand(domain, brandKey);
  if ('notFound' in brand) return json({ error: 'brand-not-found', domain }, 404);
  if ('error' in brand) return json({ error: 'extract-failed' }, 502);

  const d = brand.data || {};
  const name: string = (d.name && String(d.name).trim()) || domain;
  const colourHex = pickColour(d.colors);
  const logoUrl = pickLogo(d.logos);
  const font = pickFont(d.fonts);

  // Microcopy is optional enrichment — never fails the request.
  const context = [d.description, (d.industries || []).map((i: any) => i?.name).filter(Boolean).join(', ')]
    .filter(Boolean)
    .join(' — ');
  const { copy, copyAB } = await generateCopy(name, context);

  const profile: BrandProfile = {
    name,
    domain,
    logoUrl,
    colors: colourHex ? { primary: colourHex, onPrimary: onColour(colourHex) } : null,
    font,
    copy,
    ...(copyAB ? { copyAB } : {}),
    source: 'brandfetch',
  };

  // Store in cache (best-effort). Skipped in A/B mode so results stay live.
  if (supabase && useCache) {
    try {
      await supabase
        .from('brand_previews')
        .upsert({ domain, profile, fetched_at: new Date().toISOString() }, { onConflict: 'domain' });
    } catch (_) {
      /* non-fatal */
    }
  }

  return json(profile);
});
