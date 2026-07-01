/**
 * Shared brand re-skin helpers for the mockup checkout.
 *
 * Used by both the manual BrandStudio (/work/) and the URL-driven PreviewStudio
 * (/preview/). Pure, framework-free functions so they can be imported into any
 * Astro client <script>.
 */

/**
 * WCAG-ish luminance pick: returns the ink/paper colour that reads on top of a
 * given brand hex. Mirrors the original BrandStudio rule (threshold 0.42).
 */
export function readable(hex) {
  const c = String(hex || '').replace('#', '');
  if (c.length !== 6) return '#ffffff';
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  const lin = (v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.42 ? '#0f172a' : '#ffffff';
}

/** Two-letter monogram from a business name (fallback when no logo). */
export function initials(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return 'YB';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** URL-safe slug from a business name. */
export function slugify(name) {
  const s = String(name || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || 'your-business';
}

/**
 * Checkout scenarios. `path` is the trailing pay-URL segment; the host is built
 * by each studio (BrandStudio uses a slug, PreviewStudio uses the real domain).
 */
export const SCENARIOS = {
  invoice: { headline: 'Pay Your Invoice', amount: '480.00', pay: (a) => 'Pay £' + a, path: 'checkout' },
  deposit: { headline: 'Pay Your Deposit', amount: '150.00', pay: () => 'Pay Deposit', path: 'deposit' },
  membership: { headline: 'Start Your Membership', amount: '29.00', pay: () => 'Start Membership', path: 'join' },
};
