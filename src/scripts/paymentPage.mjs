/**
 * Painter for PaymentPagePreview — turns a validated design brief (from the
 * brand-preview function) plus manual overrides into CSS custom properties and
 * data-pp-* slot fills on ONE server-rendered card.
 *
 * Pure resolve step (resolveBrief) is separated from the DOM step (paintBrief)
 * so overrides re-render without re-fetching. The painter never creates nodes —
 * Astro's scoped styles only exist on server-rendered markup — and only ever
 * writes textContent, `hidden` and custom properties ON THE CARD ROOT (never a
 * shared ancestor: each card carries its own brief's palette).
 */
import { readable, initials } from './brandReskin.mjs';

/** Deterministic content used by the manual scenario override + fallback brief. */
export const SCENARIO_CONTENT = {
  invoice: { headline: 'Pay Your Invoice', amount: '£480.00', payLabel: 'Pay £480.00', item: 'Invoice total', path: 'checkout' },
  deposit: { headline: 'Pay Your Deposit', amount: '£150.00', payLabel: 'Pay Deposit', item: 'Booking deposit', path: 'deposit' },
  membership: { headline: 'Start Your Membership', amount: '£29.00', payLabel: 'Start Membership', item: 'Monthly membership', path: 'join' },
  booking: { headline: 'Confirm Your Booking', amount: '£95.00', payLabel: 'Confirm Booking', item: 'Booking fee', path: 'book' },
  order: { headline: 'Complete Your Order', amount: '£64.00', payLabel: 'Pay £64.00', item: 'Order total', path: 'checkout' },
};

const RADII = { sharp: '2px', soft: '8px', round: '14px' };

function lum(hex) {
  const c = String(hex || '').replace('#', '');
  if (c.length !== 6) return 0.5;
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  const lin = (v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function rgba(hex, alpha) {
  const c = String(hex || '').replace('#', '');
  if (c.length !== 6) return 'rgba(15, 23, 42, ' + alpha + ')';
  const r = parseInt(c.slice(0, 2), 16);
  const g = parseInt(c.slice(2, 4), 16);
  const b = parseInt(c.slice(4, 6), 16);
  return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
}

function fontStack(display, brandFont) {
  if (display === 'serif') return "Georgia, 'Times New Roman', serif";
  if (display === 'brand' && brandFont) return "'" + brandFont.replace(/'/g, '') + "', system-ui, sans-serif";
  return "var(--font-primary, 'Satoshi'), system-ui, sans-serif";
}

/** Neutral brief for manual mode and failed legs — always renders something honest. */
export function defaultBrief(accentHex) {
  const s = SCENARIO_CONTENT.invoice;
  return {
    rationale: '',
    palette: { mode: 'light', pageBg: '#ffffff', headerBg: '#ffffff', surface: '#ffffff', accent: accentHex, accent2: null, ink: null },
    style: { display: 'sans', wordmarkCase: 'normal', radius: 'soft', density: 'regular' },
    header: { tagline: '', nav: [], verified: true },
    sections: {
      utilityStrip: true, phone: null, banner: false, steps: true,
      stepLabels: ['Your Details', 'Payment', 'Confirmation'],
      summary: true, altPayment: 'none', referenceNote: false, footer: true,
    },
    content: {
      scenario: 'invoice', headline: s.headline, subcopy: '', reference: '',
      lineItems: [{ label: s.item, amount: s.amount }], total: s.amount, payLabel: s.payLabel,
      methodTitle: 'Pay by Bank Transfer (BACS)', methodNote: 'No fees — preferred payment method',
      referenceNoteText: 'Please include your name and reference so we can match your payment.',
      reassurance: 'A receipt is emailed to you automatically.', footerLine: '',
    },
  };
}

/**
 * brief (+ brand assets, + manual overrides) → flat render model.
 * brand: { logoUrl, logoDarkUrl, bannerUrl, font } from the v2 response.
 * overrides: { accent: hex|null, scenario: key|null } from the manual controls.
 */
export function resolveBrief(brief, brand, overrides) {
  const p = brief.palette;
  const accent = overrides.accent || p.accent;
  const ink = p.ink || readable(p.pageBg);
  const accent2 = p.accent2 || accent;

  // The strip/footer band is always a dark surface: first sufficiently dark
  // brand colour wins, with a neutral charcoal fallback.
  const stripBg = [p.headerBg, accent, p.pageBg].find((h) => lum(h) <= 0.25) || '#10151f';

  // Brandfetch theme = the artwork's own colour: dark marks for light headers,
  // light (white) marks for dark headers. Wrong variant ⇒ monogram, never invisible.
  const headerLight = lum(p.headerBg) > 0.42;
  const logoUrl = (headerLight ? brand.logoUrl : brand.logoDarkUrl) || null;

  let content = brief.content;
  if (overrides.scenario && overrides.scenario !== content.scenario) {
    const s = SCENARIO_CONTENT[overrides.scenario];
    content = {
      ...content,
      scenario: overrides.scenario,
      headline: s.headline,
      lineItems: [{ label: s.item, amount: s.amount }],
      total: s.amount,
      payLabel: s.payLabel,
      reference: '',
    };
  }

  return {
    vars: {
      '--pp-accent': accent,
      '--pp-on-accent': readable(accent),
      '--pp-accent2': accent2,
      '--pp-page-bg': p.pageBg,
      '--pp-header-bg': p.headerBg,
      '--pp-on-header': readable(p.headerBg),
      '--pp-surface': p.surface,
      '--pp-ink': ink,
      '--pp-muted': rgba(ink, 0.62),
      '--pp-line': rgba(ink, 0.16),
      '--pp-strip-bg': stripBg,
      '--pp-strip-ic': lum(accent2) >= 0.12 ? accent2 : 'rgba(255, 255, 255, 0.6)',
      '--pp-radius': RADII[brief.style.radius] || RADII.soft,
      '--pp-display-font': fontStack(brief.style.display, brand.font),
      '--pp-banner': brief.sections.banner && brand.bannerUrl ? 'url("' + encodeURI(brand.bannerUrl) + '")' : 'none',
    },
    upper: brief.style.wordmarkCase === 'upper',
    compact: brief.style.density === 'compact',
    logoUrl,
    header: brief.header,
    sections: brief.sections,
    content,
  };
}

const q = (root, sel) => root.querySelector(sel);
const qa = (root, sel) => Array.from(root.querySelectorAll(sel));

/**
 * Apply one resolved brief to one SSR'd card.
 * shared: { name, host } — the brand fields identical across cards.
 */
export function paintBrief(cardRoot, r, shared) {
  const el = q(cardRoot, '[data-pp]');
  if (!el) return;

  for (const [k, v] of Object.entries(r.vars)) el.style.setProperty(k, v);
  el.classList.toggle('pp--upper', r.upper);
  el.classList.toggle('pp--compact', r.compact);

  const setText = (sel, text) => {
    const n = q(el, sel);
    if (n) n.textContent = text;
  };
  const toggle = (sel, show) => {
    const n = q(el, sel);
    if (n) n.hidden = !show;
  };

  // Browser-chrome URL (svg is prepended back after textContent wipes it).
  const url = q(el, '.mok__url');
  if (url) {
    const icon = url.querySelector('svg');
    url.textContent = 'pay.' + shared.host + '/' + (SCENARIO_CONTENT[r.content.scenario] || SCENARIO_CONTENT.invoice).path;
    if (icon) url.prepend(icon);
  }

  // Utility strip.
  toggle('[data-pp-strip]', r.sections.utilityStrip);
  toggle('[data-pp-phone-wrap]', !!r.sections.phone);
  if (r.sections.phone) setText('[data-pp-phone]', r.sections.phone);

  // Header: monogram/wordmark vs logo, tagline, nav vs verified chip.
  setText('[data-pp-mono]', initials(shared.name));
  setText('[data-pp-name]', shared.name);
  toggle('[data-pp-tagline]', !!r.header.tagline);
  if (r.header.tagline) setText('[data-pp-tagline]', r.header.tagline);
  const navItems = qa(el, '[data-pp-nav-item]');
  const nav = r.header.nav || [];
  toggle('[data-pp-nav]', nav.length > 0);
  navItems.forEach((n, i) => {
    n.hidden = !nav[i];
    n.textContent = nav[i] || '';
  });
  toggle('[data-pp-verified]', r.header.verified && !nav.length);

  const brandRow = q(el, '[data-pp-brand]');
  const logo = q(el, '[data-pp-logo]');
  if (brandRow && logo) {
    if (r.logoUrl) {
      logo.alt = shared.name + ' logo';
      if (logo.getAttribute('src') !== r.logoUrl) {
        logo.onload = () => { logo.hidden = false; brandRow.classList.add('has-logo'); };
        logo.onerror = () => { logo.hidden = true; brandRow.classList.remove('has-logo'); };
        logo.src = r.logoUrl;
      } else if (logo.complete && logo.naturalWidth) {
        logo.hidden = false;
        brandRow.classList.add('has-logo');
      }
    } else {
      logo.hidden = true;
      logo.removeAttribute('src');
      brandRow.classList.remove('has-logo');
    }
  }

  // Banner + steps.
  toggle('[data-pp-banner]', r.vars['--pp-banner'] !== 'none');
  toggle('[data-pp-steps]', r.sections.steps);
  qa(el, '[data-pp-step]').forEach((s, i) => {
    s.textContent = r.sections.stepLabels[i] || '';
  });

  // View head.
  setText('[data-pp-headline]', r.content.headline);
  toggle('[data-pp-subcopy]', !!r.content.subcopy);
  if (r.content.subcopy) setText('[data-pp-subcopy]', r.content.subcopy);
  setText('[data-pp-total-top]', r.content.total);
  toggle('[data-pp-ref]', !!r.content.reference);
  if (r.content.reference) setText('[data-pp-ref]', r.content.reference);

  // Summary rows (pre-rendered ×4 — fill and unhide what the brief uses).
  toggle('[data-pp-summary]', r.sections.summary);
  const rows = qa(el, '[data-pp-item]');
  rows.forEach((row, i) => {
    const item = r.content.lineItems[i];
    row.hidden = !item;
    if (item) {
      const label = row.querySelector('[data-pp-item-label]');
      const amount = row.querySelector('[data-pp-item-amount]');
      if (label) label.textContent = item.label;
      if (amount) amount.textContent = item.amount;
    }
  });
  setText('[data-pp-total]', r.content.total);

  // BACS panel + reference note.
  toggle('[data-pp-method]', r.sections.altPayment === 'bacs');
  setText('[data-pp-method-title]', r.content.methodTitle);
  setText('[data-pp-method-note]', r.content.methodNote);
  setText('[data-pp-bacs-name]', shared.name);
  toggle('[data-pp-note]', r.sections.referenceNote);
  setText('[data-pp-note-text]', r.content.referenceNoteText);

  // Pay button, reassurance, footer.
  setText('[data-pp-pay]', r.content.payLabel);
  toggle('[data-pp-reassure]', !!r.content.reassurance);
  setText('[data-pp-reassure-text]', r.content.reassurance);
  toggle('[data-pp-footer]', r.sections.footer);
  toggle('[data-pp-footer-text]', !!r.content.footerLine);
  if (r.content.footerLine) setText('[data-pp-footer-text]', r.content.footerLine);
}
