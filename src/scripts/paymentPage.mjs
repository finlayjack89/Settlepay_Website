/**
 * Painter for PaymentPagePreview — applies a variant's materialised design
 * system (tokens derived server-side from the brief's brand seeds) plus manual
 * overrides to ONE server-rendered card.
 *
 * The server is the single source of colour truth: both renditions of a brand
 * are derived there by fixed formulas, so light and dark stay consistent with
 * each other and across retries. The client only picks a rendition, applies
 * overrides, and fills slots. The painter never creates nodes — Astro's scoped
 * styles only exist on server-rendered markup — and only ever writes
 * textContent, `hidden` and custom properties ON THE CARD ROOT (never a shared
 * ancestor: each card carries its own design system).
 */
import { readable, initials } from './brandReskin.mjs';

/** Deterministic content used by the manual scenario override + fallback variant. */
export const SCENARIO_CONTENT = {
  invoice: { headline: 'Pay Your Invoice', amount: '£480.00', payLabel: 'Pay £480.00', item: 'Invoice total', path: 'checkout' },
  deposit: { headline: 'Pay Your Deposit', amount: '£150.00', payLabel: 'Pay Deposit', item: 'Booking deposit', path: 'deposit' },
  membership: { headline: 'Start Your Membership', amount: '£29.00', payLabel: 'Start Membership', item: 'Monthly membership', path: 'join' },
  booking: { headline: 'Confirm Your Booking', amount: '£95.00', payLabel: 'Confirm Booking', item: 'Booking fee', path: 'book' },
  order: { headline: 'Complete Your Order', amount: '£64.00', payLabel: 'Pay £64.00', item: 'Order total', path: 'checkout' },
};

const RADII = { sharp: '2px', soft: '8px', round: '14px' };

function fontStack(display, brandFont) {
  if (display === 'serif') return "Georgia, 'Times New Roman', serif";
  if (display === 'brand' && brandFont) return "'" + brandFont.replace(/'/g, '') + "', system-ui, sans-serif";
  return "var(--font-primary, 'Satoshi'), system-ui, sans-serif";
}

/**
 * Neutral variant for manual mode and failed legs. Hand-written token sets (not
 * derived) — the server's token engine is the source of truth for real brands;
 * this is just an honest placeholder in SettlePay-neutral colours.
 */
export function defaultVariant(accentHex) {
  const s = SCENARIO_CONTENT.invoice;
  const on = readable(accentHex);
  return {
    brief: {
      rationale: '',
      design: { primary: accentHex, accent: null, pageStyle: 'paper', headerStyle: 'paper', preferred: 'light' },
      desktop: { layout: 'centered', summarySide: 'left' },
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
    },
    tokens: {
      light: {
        page: '#ffffff', header: '#ffffff', onHeader: '#1b2330', surface: '#ffffff',
        ink: '#1b2330', muted: 'rgba(15, 23, 42, 0.62)', line: 'rgba(15, 23, 42, 0.16)',
        action: accentHex, onAction: on, accent2: accentHex,
        stripBg: '#10151f', onStrip: 'rgba(255, 255, 255, 0.78)', stripIc: 'rgba(255, 255, 255, 0.6)',
        noteBg: '#f1f5f9', noteBorder: 'rgba(15, 23, 42, 0.16)',
      },
      dark: {
        page: '#10151f', header: '#151c29', onHeader: '#eef1f6', surface: '#1a2230',
        ink: '#eef1f6', muted: 'rgba(238, 241, 246, 0.62)', line: 'rgba(238, 241, 246, 0.16)',
        action: accentHex, onAction: on, accent2: accentHex,
        stripBg: '#0b0f16', onStrip: 'rgba(255, 255, 255, 0.78)', stripIc: 'rgba(255, 255, 255, 0.6)',
        noteBg: '#1d2635', noteBorder: 'rgba(238, 241, 246, 0.2)',
      },
    },
    logo: {
      light: { src: null, chip: null },
      dark: { src: null, chip: null },
    },
  };
}

/**
 * variant ({brief, tokens, logo}) + brand assets + manual overrides → flat
 * render model. overrides: { accent, scenario, device: 'mobile'|'desktop',
 * theme: 'light'|'dark'|null } — theme null = the brief's preferred rendition.
 */
export function resolveBrief(variant, brand, overrides) {
  const { brief } = variant;
  const theme = overrides.theme || brief.design.preferred || 'light';
  const t = variant.tokens[theme] || variant.tokens.light;
  const logo = (variant.logo && variant.logo[theme]) || { src: null, chip: null };
  const desktop = overrides.device === 'desktop';

  // Manual accent override swaps the ACTION colour only — the rest of the
  // design system (its neutrals, header, strip) stays the model's design.
  const action = overrides.accent || t.action;
  const onAction = overrides.accent ? readable(action) : t.onAction;

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
      '--pp-accent': action,
      '--pp-on-accent': onAction,
      '--pp-accent2': t.accent2,
      '--pp-page-bg': t.page,
      '--pp-header-bg': t.header,
      '--pp-on-header': t.onHeader,
      '--pp-surface': t.surface,
      '--pp-ink': t.ink,
      '--pp-muted': t.muted,
      '--pp-line': t.line,
      '--pp-strip-bg': t.stripBg,
      '--pp-on-strip': t.onStrip,
      '--pp-strip-ic': t.stripIc,
      '--pp-note-bg': t.noteBg,
      '--pp-note-border': t.noteBorder,
      '--pp-logo-chip': logo.chip || 'transparent',
      '--pp-radius': RADII[brief.style.radius] || RADII.soft,
      '--pp-display-font': fontStack(brief.style.display, brand.font),
      '--pp-banner': brief.sections.banner && brand.bannerUrl ? 'url("' + encodeURI(brand.bannerUrl) + '")' : 'none',
    },
    upper: brief.style.wordmarkCase === 'upper',
    compact: brief.style.density === 'compact',
    desktop,
    centered: (brief.desktop || {}).layout !== 'split',
    summaryRight: (brief.desktop || {}).summarySide === 'right',
    // Mobile hides the nav via CSS, so the chip can stand in; on desktop the
    // nav wins the header's right-hand slot.
    showVerified: brief.header.verified && (!desktop || !(brief.header.nav || []).length),
    logoUrl: logo.src,
    logoChip: !!logo.chip,
    header: brief.header,
    sections: brief.sections,
    content,
  };
}

const q = (root, sel) => root.querySelector(sel);
const qa = (root, sel) => Array.from(root.querySelectorAll(sel));

/**
 * Apply one resolved variant to one SSR'd card.
 * shared: { name, host } — the brand fields identical across cards.
 */
export function paintBrief(cardRoot, r, shared) {
  const el = q(cardRoot, '[data-pp]');
  if (!el) return;

  for (const [k, v] of Object.entries(r.vars)) el.style.setProperty(k, v);
  el.classList.toggle('pp--upper', r.upper);
  el.classList.toggle('pp--compact', r.compact);
  el.classList.toggle('pp--desktop', r.desktop);
  el.classList.toggle('pp--centered', r.centered);
  el.classList.toggle('pp--summary-right', r.summaryRight);

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
  toggle('[data-pp-verified]', r.showVerified);

  const brandRow = q(el, '[data-pp-brand]');
  const logo = q(el, '[data-pp-logo]');
  if (brandRow && logo) {
    logo.classList.toggle('pp__logo--chip', r.logoChip);
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
