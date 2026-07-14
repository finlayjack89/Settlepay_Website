// `brand-preview` Edge Function — powers the /preview/ "see your payment page" tool.
//
// v2: takes a visitor's website URL, reads their public brand via Brandfetch
// (all colours, themed logos, banner, font, description) plus a Firecrawl
// homepage screenshot + copy excerpt, then asks each active model (see
// providers.ts) for a full DESIGN BRIEF — palette, layout sections, typography
// feel and industry-authentic content — validated by spec.ts before it ships.
// The front-end renders one full payment page per returned brief; in
// split-test mode all legs render side by side.
//
// Also accepts `{vote:{domain,key,model}}` — the "prefer this design" tally.
//
// Public endpoint: deploy with `--no-verify-jwt` (anonymous POST), exactly like
// the `enquiry` function. Always returns a clean JSON envelope — the front-end
// falls back to manual entry on any error.
//
// Env (function secrets — see .env.example):
//   BRANDFETCH_API_KEY   required for live previews
//   FIRECRAWL_API_KEY    optional homepage screenshot + markdown (degrades gracefully)
//   ANTHROPIC_API_KEY    Claude legs        OPENAI_API_KEY  GPT legs
//   DESIGN_PROVIDERS     comma list of haiku,sonnet,luna,terra (1 = production+cache)
//   SONNET_MODEL / OPENAI_REASONING_EFFORT / ALLOWED_ORIGIN
//   RATE_LIMIT_PER_MIN / RATE_LIMIT_PER_DAY / CACHE_TTL_HOURS

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import {
  type BrandColour,
  briefUserPrompt,
  deriveLogo,
  deriveTokens,
  harvestColours,
  pickColour,
  snapAccent,
  validateSpec,
} from './spec.ts';
import { activeProviders, PROVIDERS, runDesigners } from './providers.ts';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';
const MULTI = activeProviders().length > 1;
// Each request bills every active leg (+ Firecrawl + Brandfetch) — throttle
// harder while the split test runs.
const RATE_LIMIT_PER_MIN = Number(Deno.env.get('RATE_LIMIT_PER_MIN') ?? (MULTI ? '5' : '10'));
const RATE_LIMIT_PER_DAY = Number(Deno.env.get('RATE_LIMIT_PER_DAY') ?? '60');
const CACHE_TTL_HOURS = Number(Deno.env.get('CACHE_TTL_HOURS') ?? '168');

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

/** First usable src for a logo entry. `raster` skips SVG (vision APIs reject it). */
function fmtSrc(entry: any, raster = false): string | null {
  const formats: any[] = Array.isArray(entry?.formats) ? entry.formats : [];
  const order = raster ? ['png', 'jpeg', 'webp'] : ['svg', 'png', 'jpeg', 'webp'];
  for (const fmt of order) {
    const f = formats.find((x) => x?.format === fmt && x?.src);
    if (f) return f.src;
  }
  return raster ? null : formats.find((x) => x?.src)?.src ?? null;
}

/**
 * Themed logo picks. Brandfetch `theme` describes the ARTWORK: 'dark' = dark
 * marks for light backgrounds, 'light' = white marks for dark backgrounds
 * (verified against github.com — the v1 comment had it backwards).
 */
function pickLogos(logos: any[]) {
  const all = (logos || []).filter((l) => Array.isArray(l?.formats) && l.formats.length);
  const byScore = (want: 'dark' | 'light') =>
    [...all]
      .filter((l) => ['logo', 'symbol', 'icon'].includes(String(l.type).toLowerCase()))
      .sort((a, b) => score(b, want) - score(a, want))[0] ?? null;
  const score = (l: any, want: 'dark' | 'light') => {
    const type = String(l.type).toLowerCase();
    const theme = String(l.theme ?? '').toLowerCase();
    let s = 0;
    if (type === 'logo') s += 4;
    else if (type === 'symbol' || type === 'icon') s += 2;
    if (theme === want) s += 3;
    else if (theme === '') s += 1;
    return s;
  };
  const forLight = byScore('dark'); // dark artwork reads on light headers
  const forDark = byScore('light');
  const icon = all.find((l) => ['icon', 'symbol'].includes(String(l.type).toLowerCase()));
  return {
    logoUrl: forLight ? fmtSrc(forLight) : null,
    logoDarkUrl: forDark && String(forDark.theme).toLowerCase() === 'light' ? fmtSrc(forDark) : null,
    iconUrl: icon ? fmtSrc(icon) : null,
    logoRasterUrl: forLight ? fmtSrc(forLight, true) : null,
  };
}

/** Brandfetch font names can be scraping garbage (`var(--ricos-font-family`). */
function pickFont(fonts: any[]): string | null {
  const sane = (name: unknown) =>
    typeof name === 'string' &&
    /^[A-Za-z0-9][A-Za-z0-9 '\-]{1,39}$/.test(name.trim()) &&
    !/var|--|[(),;]/.test(name);
  const valid = (fonts || []).filter((f) => sane(f?.name));
  if (!valid.length) return null;
  const title = valid.find((f) => String(f.type).toLowerCase() === 'title');
  return (title || valid[0]).name.trim();
}

function pickBanner(images: any[]): string | null {
  const banner = (images || []).find(
    (i) => String(i?.type).toLowerCase() === 'banner' && Array.isArray(i?.formats) && i.formats.length,
  );
  return banner ? fmtSrc(banner, true) : null;
}

// ---- Firecrawl (screenshot + homepage copy — best-effort) --------------------

async function fetchSite(domain: string): Promise<{
  screenshotUrl: string | null;
  markdown: string | null;
  cssColours: { hex: string; count: number }[];
  title: string | null;
  metaDescription: string | null;
}> {
  const none = { screenshotUrl: null, markdown: null, cssColours: [], title: null, metaDescription: null };
  const key = Deno.env.get('FIRECRAWL_API_KEY');
  if (!key) return none;
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 20_000);
    const res = await fetch('https://api.firecrawl.dev/v2/scrape', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + key, 'content-type': 'application/json' },
      body: JSON.stringify({
        url: 'https://' + domain,
        // html rides along free on the same scrape — it feeds the colour census.
        // NB v2 wants screenshot options INSIDE the formats array; a top-level
        // `screenshot` key is rejected with a 400 (verified live).
        formats: [
          'markdown',
          'html',
          { type: 'screenshot', fullPage: false, viewport: { width: 1280, height: 800 } },
        ],
      }),
      signal: ctl.signal,
    });
    clearTimeout(timer);
    if (!res.ok) {
      console.warn('firecrawl error', res.status, (await res.text().catch(() => '')).slice(0, 200));
      return none;
    }
    const body = await res.json();
    const md = typeof body?.data?.markdown === 'string' ? body.data.markdown : null;
    const meta = body?.data?.metadata || {};
    return {
      screenshotUrl: typeof body?.data?.screenshot === 'string' ? body.data.screenshot : null,
      markdown: md ? md.replace(/\s+/g, ' ').slice(0, 1500) : null,
      cssColours: harvestColours(body?.data?.html || ''),
      title: typeof meta.title === 'string' ? meta.title : null,
      metaDescription: typeof meta.description === 'string' ? meta.description : null,
    };
  } catch (e) {
    console.warn('firecrawl failed', e);
    return none;
  }
}

/** Drop image URLs the vision APIs couldn't fetch (a dead CDN link 400s a whole leg). */
async function preflightImages(
  items: { url: string | null; hi?: boolean }[],
): Promise<{ url: string; hi?: boolean }[]> {
  const candidates = items.filter((i): i is { url: string; hi?: boolean } => !!i.url).slice(0, 3);
  const checks = await Promise.all(
    candidates.map(async (i) => {
      try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 4_000);
        const res = await fetch(i.url, { method: 'HEAD', signal: ctl.signal });
        clearTimeout(timer);
        return res.ok ? i : null;
      } catch {
        return null;
      }
    }),
  );
  return checks.filter((i): i is { url: string; hi?: boolean } => !!i);
}

// ---- handler ---------------------------------------------------------------

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  let payload: {
    url?: string;
    fresh?: boolean; // deliberate re-roll: skip the cache read (the write still happens)
    vote?: { domain?: string; key?: string; model?: string };
    createShare?: { domain?: string }; // snapshot the cached design → { slug }
    share?: { slug?: string }; // fetch a share snapshot for the /p/ page
    renderShare?: { slug?: string; device?: string; theme?: string }; // download: screenshot the render page → image bytes
  };
  try {
    payload = await req.json();
  } catch {
    return json({ error: 'invalid-json' }, 400);
  }

  // Best-effort Supabase client for cache + rate-limit + votes.
  let supabase: ReturnType<typeof createClient> | null = null;
  try {
    const sbUrl = Deno.env.get('SUPABASE_URL');
    const sbKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
    if (sbUrl && sbKey) supabase = createClient(sbUrl, sbKey);
  } catch (_) {
    supabase = null;
  }

  const ip = (req.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'unknown';
  const ipHash = await hashIp(ip);

  // ---- vote branch -----------------------------------------------------------
  if (payload.vote) {
    const domain = toDomain(payload.vote.domain || '');
    const key = String(payload.vote.key || '');
    const model = String(payload.vote.model || '').slice(0, 64);
    if (!domain || !(key in PROVIDERS)) return json({ error: 'invalid-vote' }, 400);
    if (!supabase) return json({ error: 'vote-unavailable' }, 503);
    const { error } = await supabase
      .from('brand_preview_votes')
      .insert({ domain, variant_key: key, model, ip_hash: ipHash });
    if (error) {
      console.error('vote insert failed', error.message);
      return json({ error: 'vote-failed' }, 500);
    }
    return json({ ok: true });
  }

  // ---- share branches ----------------------------------------------------------
  // Create: snapshot the SERVER-side cached design (never client-supplied JSON —
  // the /p/ page must only ever render pipeline-validated content).
  if (payload.createShare) {
    const shareDomain = toDomain(payload.createShare.domain || '');
    if (!shareDomain) return json({ error: 'invalid-domain' }, 400);
    if (!supabase) return json({ error: 'share-unavailable' }, 503);
    try {
      const { data: cached } = await supabase
        .from('brand_previews')
        .select('profile, fetched_at')
        .eq('domain', shareDomain)
        .maybeSingle();
      const profile = cached?.profile;
      const fresh =
        cached?.fetched_at && Date.now() - new Date(cached.fetched_at).getTime() < CACHE_TTL_HOURS * 3_600_000;
      const variant = profile?.v === 4 && fresh ? (profile.variants || []).find((v: any) => v.brief && v.tokens) : null;
      if (!variant) return json({ error: 'nothing-to-share' }, 404);

      // Unguessable slug: 12 chars over a 31-symbol alphabet ≈ 59 bits.
      const alphabet = 'abcdefghjkmnpqrstuvwxyz23456789';
      const bytes = crypto.getRandomValues(new Uint8Array(12));
      const slug = [...bytes].map((b) => alphabet[b % alphabet.length]).join('');

      const snapshot = {
        name: profile.name,
        domain: profile.domain,
        brand: profile.brand,
        variant: { brief: variant.brief, tokens: variant.tokens, logo: variant.logo },
      };
      const { error } = await supabase.from('brand_preview_shares').insert({ slug, domain: shareDomain, snapshot });
      if (error) throw new Error(error.message);
      return json({ slug });
    } catch (e) {
      console.error('createShare failed', e);
      return json({ error: 'share-failed' }, 500);
    }
  }

  // Fetch: the /p/ page loads a snapshot by slug.
  if (payload.share) {
    const slug = String(payload.share.slug || '').toLowerCase();
    if (!/^[a-z0-9]{8,16}$/.test(slug)) return json({ error: 'invalid-share' }, 400);
    if (!supabase) return json({ error: 'share-unavailable' }, 503);
    try {
      const { data: row } = await supabase
        .from('brand_preview_shares')
        .select('snapshot, expires_at, views')
        .eq('slug', slug)
        .maybeSingle();
      if (!row) return json({ error: 'share-not-found' }, 404);
      if (new Date(row.expires_at).getTime() < Date.now()) return json({ error: 'share-expired' }, 404);
      await supabase.rpc('bump_share_views', { share_slug: slug }).then(
        () => {},
        () => {}, // view counting is best-effort
      );
      return json({ v: 4, share: true, views: (row.views ?? 0) + 1, ...row.snapshot });
    } catch (e) {
      console.error('share fetch failed', e);
      return json({ error: 'share-failed' }, 500);
    }
  }

  // Download: Firecrawl screenshots the production /p/render/ page for this
  // share and the image bytes are proxied straight back (their signed URL has
  // no CORS for browser fetches). Costs one Firecrawl credit per call, so it
  // shares the per-minute rate limit with generation.
  if (payload.renderShare) {
    const slug = String(payload.renderShare.slug || '').toLowerCase();
    if (!/^[a-z0-9]{8,16}$/.test(slug)) return json({ error: 'invalid-share' }, 400);
    const device = payload.renderShare.device === 'desktop' ? 'desktop' : 'mobile';
    const theme = ['light', 'dark'].includes(payload.renderShare.theme || '') ? payload.renderShare.theme : '';
    const fcKey = Deno.env.get('FIRECRAWL_API_KEY');
    if (!supabase || !fcKey) return json({ error: 'render-unavailable' }, 503);

    try {
      const { data: row } = await supabase
        .from('brand_preview_shares')
        .select('slug, expires_at')
        .eq('slug', slug)
        .maybeSingle();
      if (!row || new Date(row.expires_at).getTime() < Date.now()) return json({ error: 'share-not-found' }, 404);

      if (RATE_LIMIT_PER_MIN > 0) {
        const since = new Date(Date.now() - 60_000).toISOString();
        const { count } = await supabase
          .from('brand_preview_requests')
          .select('id', { count: 'exact', head: true })
          .eq('ip_hash', ipHash)
          .gte('created_at', since);
        if ((count ?? 0) >= RATE_LIMIT_PER_MIN) return json({ error: 'rate-limited' }, 429);
        await supabase.from('brand_preview_requests').insert({ ip_hash: ipHash, domain: 'render:' + slug });
      }

      const base = Deno.env.get('RENDER_BASE') ?? 'https://settlepay.uk';
      // 4K-class output: the render page zooms itself by `scale` (Firecrawl has
      // no deviceScaleFactor) and the capture viewport grows to match — desktop
      // lands at 3520px wide, mobile at 2160px. Text and layout stay vector-
      // crisp; raster logos are as sharp as their source allows.
      const scale = Math.min(4, Math.max(1, Number(Deno.env.get('RENDER_SCALE') ?? '4') || 4));
      const target =
        base + '/p/render/?s=' + slug + '&device=' + device + (theme ? '&theme=' + theme : '') + '&scale=' + scale;
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 30_000);
      const shot = await fetch('https://api.firecrawl.dev/v2/scrape', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + fcKey, 'content-type': 'application/json' },
        body: JSON.stringify({
          url: target,
          formats: [
            {
              type: 'screenshot',
              fullPage: true,
              viewport: { width: (device === 'desktop' ? 880 : 540) * scale, height: 900 },
            },
          ],
          waitFor: 4000, // fetch + paint + logo load + zoomed decode
        }),
        signal: ctl.signal,
      });
      clearTimeout(timer);
      if (!shot.ok) {
        console.error('render screenshot failed', shot.status, (await shot.text().catch(() => '')).slice(0, 200));
        return json({ error: 'render-failed' }, 502);
      }
      const body = await shot.json();
      const imgUrl = body?.data?.screenshot;
      if (typeof imgUrl !== 'string') return json({ error: 'render-failed' }, 502);
      const img = await fetch(imgUrl);
      if (!img.ok) return json({ error: 'render-failed' }, 502);
      const contentType = img.headers.get('content-type') || 'image/png';
      return new Response(await img.arrayBuffer(), {
        headers: {
          ...cors,
          'content-type': contentType,
          'content-disposition': 'attachment; filename="settlepay-preview.' + (contentType.includes('jpeg') ? 'jpg' : 'png') + '"',
        },
      });
    } catch (e) {
      console.error('renderShare failed', e);
      return json({ error: 'render-failed' }, 500);
    }
  }

  // ---- generate branch ---------------------------------------------------------
  const domain = toDomain(payload.url || '');
  if (!domain) return json({ error: 'invalid-url' }, 400);

  const brandKey = Deno.env.get('BRANDFETCH_API_KEY');
  if (!brandKey) {
    console.warn('BRANDFETCH_API_KEY not set — live previews disabled.');
    return json({ error: 'not-configured' }, 503);
  }

  // Rate-limit by hashed IP: per-minute and per-day windows on the same table.
  if (supabase && (RATE_LIMIT_PER_MIN > 0 || RATE_LIMIT_PER_DAY > 0)) {
    try {
      const windows: Array<[number, number]> = [
        [RATE_LIMIT_PER_MIN, 60_000],
        [RATE_LIMIT_PER_DAY, 86_400_000],
      ];
      for (const [limit, ms] of windows) {
        if (limit <= 0) continue;
        const since = new Date(Date.now() - ms).toISOString();
        const { count } = await supabase
          .from('brand_preview_requests')
          .select('id', { count: 'exact', head: true })
          .eq('ip_hash', ipHash)
          .gte('created_at', since);
        if ((count ?? 0) >= limit) return json({ error: 'rate-limited' }, 429);
      }
      await supabase.from('brand_preview_requests').insert({ ip_hash: ipHash, domain });
    } catch (_) {
      /* table missing or transient — skip the limiter */
    }
  }

  // ---- cache: two levels, active in every mode ---------------------------------
  // Level 1: same domain + same provider set → return the stored response whole
  // (design systems + pages), zero model/Firecrawl spend. Level 2: provider set
  // changed → reuse the stored brand extraction, re-run only the model legs.
  const providersSig = activeProviders().join(',');
  let extract: any = null;
  if (supabase && !payload.fresh) {
    try {
      const { data: cached } = await supabase
        .from('brand_previews')
        .select('profile, fetched_at')
        .eq('domain', domain)
        .maybeSingle();
      if (cached?.profile?.v === 4 && cached.fetched_at) {
        const ageMs = Date.now() - new Date(cached.fetched_at).getTime();
        if (ageMs < CACHE_TTL_HOURS * 3_600_000) {
          if (cached.profile.providers === providersSig) {
            const { extract: _hidden, ...body } = cached.profile;
            return json({ ...body, cached: true });
          }
          extract = cached.profile.extract ?? null;
        }
      }
    } catch (_) {
      /* cache miss path */
    }
  }

  if (!extract) {
    // Brand extraction and site capture are independent — run them together.
    const [brand, site] = await Promise.all([fetchBrand(domain, brandKey), fetchSite(domain)]);

    if ('data' in brand) {
      const d = brand.data || {};
      extract = {
        name: (d.name && String(d.name).trim()) || domain,
        colors: (d.colors || []).filter((c: any) => typeof c?.hex === 'string'),
        logos: pickLogos(d.logos),
        font: pickFont(d.fonts),
        bannerUrl: pickBanner(d.images),
        description: String(d.description || '').slice(0, 400),
        industries: (d.company?.industries || d.industries || [])
          .map((i: any) => (typeof i === 'string' ? i : i?.name))
          .filter(Boolean)
          .slice(0, 3),
        markdown: site.markdown,
        screenshotUrl: site.screenshotUrl,
        cssColours: site.cssColours,
        source: 'brandfetch',
      };
    } else if (site.screenshotUrl || site.markdown) {
      // Brandfetch doesn't index most small businesses — exactly our audience.
      // The site itself carries everything the designers need: screenshot,
      // copy, colour census, page title. No logo → monogram fallback.
      const rawTitle = (site.title || '').split(/\s+[|—–·:-]\s+/)[0].trim();
      extract = {
        name: rawTitle.slice(0, 40) || domain.split('.')[0].replace(/^./, (c: string) => c.toUpperCase()),
        colors: (site.cssColours || []).slice(0, 6).map((c) => ({ hex: c.hex, type: 'css' })),
        logos: { logoUrl: null, logoDarkUrl: null, iconUrl: null, logoRasterUrl: null },
        font: null,
        bannerUrl: null,
        description: String(site.metaDescription || '').slice(0, 400),
        industries: [],
        markdown: site.markdown,
        screenshotUrl: site.screenshotUrl,
        cssColours: site.cssColours,
        source: 'site',
      };
      console.log('brand-preview site-only fallback', domain);
    } else if ('error' in brand) {
      return json({ error: 'extract-failed' }, 502);
    } else {
      return json({ error: 'brand-not-found', domain }, 404);
    }
  }

  const name: string = extract.name;
  const colors: BrandColour[] = extract.colors;
  const logos = extract.logos as ReturnType<typeof pickLogos>;
  const font: string | null = extract.font;
  const bannerUrl: string | null = extract.bannerUrl;

  // Vision inputs: screenshot beats banner beats logo; max 3, all pre-flighted
  // (a cached Firecrawl screenshot URL may have expired — the pre-flight drops it).
  const images = await preflightImages([
    { url: extract.screenshotUrl, hi: true },
    { url: bannerUrl },
    { url: logos.logoRasterUrl },
  ]);
  const imageNote = images.length
    ? 'Images attached in order: ' +
      [extract.screenshotUrl && 'homepage screenshot', bannerUrl && 'brand banner', logos.logoRasterUrl && 'logo']
        .filter(Boolean)
        .slice(0, images.length)
        .join(', ') +
      '.'
    : '';

  const userText = briefUserPrompt({
    name,
    domain,
    description: extract.description,
    industries: extract.industries,
    colors,
    font,
    markdown: extract.markdown,
    cssColours: extract.cssColours || [],
    imageNote,
  });

  const legs = await runDesigners(activeProviders(), { userText, images });

  const brandLogos = { logoUrl: logos.logoUrl, logoDarkUrl: logos.logoDarkUrl };
  const variants = legs.map((leg) => {
    const brief = leg.brief ? validateSpec(leg.brief, { name, colors, font }) : null;
    // Ground the accent in the site's own stylesheet: models tend to echo the
    // brand-API hex (logo-sampled) even when the site paints with another tone.
    if (brief && snapAccent(brief.design, extract.cssColours || [])) {
      console.log('brand-preview accent snapped', JSON.stringify({ key: leg.key, accent: brief.design.accent }));
    }
    // Materialise the design system: both renditions derive from the brief's
    // seeds by fixed formulas, so light/dark stay consistent with each other.
    const tokens = brief
      ? { light: deriveTokens(brief.design, 'light'), dark: deriveTokens(brief.design, 'dark') }
      : null;
    const logo = tokens
      ? { light: deriveLogo(tokens.light, brandLogos), dark: deriveLogo(tokens.dark, brandLogos) }
      : null;
    // Cost tracking: tokens x the pinned per-model price, logged AND persisted.
    const price = PROVIDERS[leg.key].price;
    const cost = leg.usage
      ? Math.round((leg.usage.input_tokens * price.in + leg.usage.output_tokens * price.out)) / 1_000_000
      : null;
    if (leg.usage) {
      console.log(
        'brand-preview design usage',
        JSON.stringify({ key: leg.key, model: leg.model, ms: Math.round(leg.ms), cost_usd: cost, ...leg.usage }),
      );
    }
    return {
      key: leg.key,
      vendor: leg.vendor,
      model: leg.model,
      label: leg.label,
      brief,
      tokens,
      logo,
      ms: Math.round(leg.ms),
      usage: leg.usage,
      cost,
      ...(leg.note ? { note: leg.note } : {}),
      ...(leg.error ? { error: leg.error } : brief ? {} : { error: 'invalid-brief' }),
    };
  });

  // Durable telemetry: one row per billed leg (stdout logs rotate; this doesn't).
  let usageRecorded = 0;
  if (supabase) {
    const rows = variants
      .filter((v) => v.usage)
      .map((v) => ({
        domain,
        variant_key: v.key,
        model: v.model,
        input_tokens: v.usage!.input_tokens,
        output_tokens: v.usage!.output_tokens,
        reasoning_tokens: (v.usage as any).reasoning_tokens ?? null,
        ms: v.ms,
        cost_usd: v.cost,
      }));
    if (rows.length) {
      const { data: inserted, error } = await supabase.from('brand_preview_usage').insert(rows).select('id');
      if (error) console.error('usage insert failed', error.message);
      else usageRecorded = inserted?.length ?? 0;
    }
  }

  const profile = {
    v: 4,
    providers: providersSig,
    name,
    domain,
    brand: {
      palette: colors,
      accent: pickColour(colors),
      logoUrl: logos.logoUrl,
      logoDarkUrl: logos.logoDarkUrl,
      iconUrl: logos.iconUrl,
      bannerUrl,
      font,
      description: extract.description,
    },
    variants,
    source: extract.source || 'brandfetch',
    // Stored for provider-set changes (level-2 reuse); stripped from responses.
    extract,
  };

  if (supabase && variants.some((v) => v.brief)) {
    try {
      await supabase
        .from('brand_previews')
        .upsert({ domain, profile, fetched_at: new Date().toISOString() }, { onConflict: 'domain' });
    } catch (_) {
      /* non-fatal */
    }
  }

  const { extract: _hidden, ...body } = profile;
  // usageRecorded rides on the live response only (not the cache) — it lets the
  // caller confirm telemetry rows actually landed for THIS generation.
  return json({ ...body, usageRecorded });
});
