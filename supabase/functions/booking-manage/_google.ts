// AUTO-GENERATED from scripts/lib — DO NOT EDIT. Regenerate: node scripts/build-booking-functions.mjs
// Google service-account auth for the Deno Edge Functions.
// Mints an RS256 JWT (Web Crypto), impersonating the host via domain-wide
// delegation (sub) — required so Google Meet links generate — exchanges it for
// an access token, and caches the token in module scope (~55 min).
//
// GOOGLE_SA_KEY may be the raw service-account JSON or (recommended) that JSON
// base64-encoded, to avoid newline/quoting corruption of the private key.

interface SaKey {
  client_email: string;
  private_key: string;
  token_uri: string;
}

// The Workspace user whose calendar we book against / impersonate.
export const IMPERSONATE = 'finlay@settlepay.uk';
const SCOPE = 'https://www.googleapis.com/auth/calendar';

function parseSaKey(): SaKey {
  const raw = (Deno.env.get('GOOGLE_SA_KEY') ?? '').trim();
  if (!raw) throw new Error('GOOGLE_SA_KEY not set');
  const json = raw.startsWith('{')
    ? raw
    : new TextDecoder().decode(Uint8Array.from(atob(raw), (c) => c.charCodeAt(0)));
  const k = JSON.parse(json);
  return {
    client_email: k.client_email,
    private_key: k.private_key,
    token_uri: k.token_uri ?? 'https://oauth2.googleapis.com/token',
  };
}

function pemToBuf(pem: string): ArrayBuffer {
  const b = atob(pem.replace(/-----(BEGIN|END) PRIVATE KEY-----/g, '').replace(/\s+/g, ''));
  const u = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
  return u.buffer;
}

const importKey = (pem: string) =>
  crypto.subtle.importKey('pkcs8', pemToBuf(pem), { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['sign']);

const b64url = (u: Uint8Array) =>
  btoa(String.fromCharCode(...u)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const b64urlStr = (s: string) => b64url(new TextEncoder().encode(s));

async function signJwt(sa: SaKey): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', typ: 'JWT' };
  const claims = {
    iss: sa.client_email,
    sub: IMPERSONATE, // domain-wide-delegation impersonation → Meet links work
    scope: SCOPE,
    aud: sa.token_uri,
    iat: now,
    exp: now + 3600,
  };
  const unsigned = `${b64urlStr(JSON.stringify(header))}.${b64urlStr(JSON.stringify(claims))}`;
  const sig = new Uint8Array(
    await crypto.subtle.sign({ name: 'RSASSA-PKCS1-v1_5' }, await importKey(sa.private_key), new TextEncoder().encode(unsigned)),
  );
  return `${unsigned}.${b64url(sig)}`;
}

let cache: { token: string; exp: number } | null = null;

export async function getAccessToken(): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  if (cache && cache.exp - 60 > now) return cache.token;
  const sa = parseSaKey();
  const res = await fetch(sa.token_uri, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: await signJwt(sa),
    }),
  });
  if (!res.ok) throw new Error(`google token exchange ${res.status}: ${await res.text()}`);
  const j = await res.json();
  cache = { token: j.access_token, exp: now + (j.expires_in ?? 3600) };
  return cache.token;
}
