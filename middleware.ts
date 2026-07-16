/**
 * Vercel Edge Middleware — personalised unfurls for preview share links.
 *
 * /p/<slug> serves the static /p/ shell (see vercel.json), whose OG tags are
 * baked at build time — so every WhatsApp/LinkedIn unfurl showed the same
 * generic card. This middleware intercepts slugged share links, looks the
 * share up (same brand-preview endpoint the page itself uses), and rewrites
 * the title/description tags so the recipient sees THEIR OWN business name
 * in the chat bubble ("Marsh & Vale Plumbing's Payment Page Preview").
 *
 * Fail-safe by design: any lookup error/timeout serves the untransformed
 * shell, which is exactly what shipped before this file existed. Transformed
 * HTML is edge-cached per URL for an hour (s-maxage) so bot bursts on a
 * shared link cost one function call, not hundreds.
 *
 * v2 (not built): per-share og:image via a cached renderShare screenshot —
 * needs a storage bucket for the PNGs; the generic preview card ships until
 * then.
 */
export const config = { matcher: '/p/:path*' };

const ENDPOINT = 'https://xqpbcoldcqfxfwhcqlcy.supabase.co/functions/v1/brand-preview';
const SITE_URL = 'https://settlepay.uk';

const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export default async function middleware(req: Request): Promise<Response | undefined> {
  const url = new URL(req.url);
  const m = url.pathname.match(/^\/p\/([a-z0-9]{8,16})\/?$/i);
  const slug = (m?.[1] || url.searchParams.get('s') || '').toLowerCase();
  if (!slug) return; // plain /p/ (or /p/render) → static handling as before

  const [shellRes, shareRes] = await Promise.all([
    fetch(new URL('/p/', url.origin)),
    fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ share: { slug } }),
      signal: AbortSignal.timeout(2500),
    }).catch(() => null),
  ]);
  let html = await shellRes.text();

  let name = '';
  let domain = '';
  if (shareRes && shareRes.ok) {
    const data = await shareRes.json().catch(() => null);
    if (data && !data.error && typeof data.name === 'string' && data.name) {
      name = data.name;
      domain = typeof data.domain === 'string' ? data.domain : '';
    }
  }

  if (name) {
    const poss = name.endsWith('s') ? "'" : "'s";
    const title = `${esc(name)}${poss} Payment Page Preview | SettlePay`;
    const desc = esc(
      `An illustrative payment-page preview designed from ${domain || 'this business'}'s public branding — see how a bespoke checkout could look.`,
    );
    const shareUrl = `${SITE_URL}/p/${slug}`;
    html = html
      .replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`)
      .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${title}$2`)
      .replace(/(<meta name="twitter:title" content=")[^"]*(")/, `$1${title}$2`)
      .replace(/(<meta name="description" content=")[^"]*(")/, `$1${desc}$2`)
      .replace(/(<meta property="og:description" content=")[^"]*(")/, `$1${desc}$2`)
      .replace(/(<meta name="twitter:description" content=")[^"]*(")/, `$1${desc}$2`)
      .replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${shareUrl}$2`);
  }

  return new Response(html, {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'public, max-age=0, s-maxage=3600',
    },
  });
}
