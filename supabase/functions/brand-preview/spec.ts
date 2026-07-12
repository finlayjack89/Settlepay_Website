// spec.ts — the design-brief contract for the `brand-preview` function.
//
// The models' entire action space is the Brief JSON below. The prompt asks for
// good output; validateSpec() GUARANTEES safe output — whitelist-walk (raw model
// JSON is never spread), enum fallbacks, length clamps, hex/amount/phone
// regexes, banned-phrase scrub and a deterministic contrast guard. Anything the
// validator can't repair falls back field-by-field; only a non-object response
// fails the whole brief.

// ---- types ------------------------------------------------------------------

export interface LineItem {
  label: string;
  amount: string;
}

/**
 * The materialised design system for one rendition — every colour the template
 * consumes, derived deterministically from the brief's design seeds so light
 * and dark stay consistent with each other and across regenerations.
 */
export interface ThemeTokens {
  page: string;
  header: string;
  onHeader: string;
  surface: string;
  ink: string;
  muted: string;
  line: string;
  action: string;
  onAction: string;
  accent2: string;
  stripBg: string;
  onStrip: string;
  stripIc: string;
  noteBg: string;
  noteBorder: string;
}

export interface LogoToken {
  src: string | null; // null → monogram chip
  chip: string | null; // backing chip colour when the artwork clashes with the header
}

export interface Brief {
  rationale: string;
  // Brand seeds — the model's design DECISIONS. Both renditions derive from these.
  design: {
    primary: string;
    accent: string | null;
    pageStyle: 'paper' | 'tinted';
    headerStyle: 'paper' | 'brand';
    preferred: 'light' | 'dark';
  };
  desktop: { layout: 'split' | 'centered'; summarySide: 'left' | 'right' };
  style: {
    display: 'serif' | 'sans' | 'brand';
    wordmarkCase: 'normal' | 'upper';
    radius: 'sharp' | 'soft' | 'round';
    density: 'compact' | 'regular';
  };
  header: { tagline: string; nav: string[]; verified: boolean };
  sections: {
    utilityStrip: boolean;
    phone: string | null;
    banner: boolean;
    steps: boolean;
    stepLabels: string[];
    summary: boolean;
    altPayment: 'bacs' | 'none';
    referenceNote: boolean;
    footer: boolean;
  };
  content: {
    scenario: 'invoice' | 'deposit' | 'membership' | 'booking' | 'order';
    headline: string;
    subcopy: string;
    reference: string;
    lineItems: LineItem[];
    total: string;
    payLabel: string;
    methodTitle: string;
    methodNote: string;
    referenceNoteText: string;
    reassurance: string;
    footerLine: string;
  };
}

export interface BrandColour {
  hex: string;
  type: string;
}

// ---- colour utilities (shared with index.ts) --------------------------------

export const isHex = (s: unknown): s is string =>
  typeof s === 'string' && /^#[0-9a-fA-F]{6}$/.test(s);

export function relLum(hex: string): number {
  const c = hex.replace('#', '');
  if (c.length !== 6) return 0.5;
  const r = parseInt(c.slice(0, 2), 16) / 255;
  const g = parseInt(c.slice(2, 4), 16) / 255;
  const b = parseInt(c.slice(4, 6), 16) / 255;
  const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** Ink or paper that reads on top of a brand hex (mirrors the client readable()). */
export function onColour(hex: string): string {
  return relLum(hex) > 0.42 ? '#0f172a' : '#ffffff';
}

export function mixHex(a: string, b: string, t: number): string {
  const pa = a.replace('#', '');
  const pb = b.replace('#', '');
  if (pa.length !== 6 || pb.length !== 6) return a;
  const ch = (i: number) => {
    const va = parseInt(pa.slice(i, i + 2), 16);
    const vb = parseInt(pb.slice(i, i + 2), 16);
    return Math.round(va + (vb - va) * t)
      .toString(16)
      .padStart(2, '0');
  };
  return '#' + ch(0) + ch(2) + ch(4);
}

export function contrastRatio(a: string, b: string): number {
  const la = relLum(a);
  const lb = relLum(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Best single brand colour: accent → brand → most mid-luminance on offer. */
export function pickColour(colors: BrandColour[]): string | null {
  const valid = (colors || []).filter((c) => isHex(c?.hex));
  if (!valid.length) return null;
  const byType = (t: string) => valid.find((c) => String(c.type).toLowerCase() === t);
  const accent = byType('accent') || byType('brand');
  if (accent) return accent.hex;
  const mid = valid
    .map((c) => ({ hex: c.hex, l: relLum(c.hex) }))
    .filter((c) => c.l > 0.05 && c.l < 0.85)
    .sort((a, b) => Math.abs(0.4 - a.l) - Math.abs(0.4 - b.l));
  return (mid[0] || valid[0]).hex;
}

// ---- deterministic fallbacks --------------------------------------------------

export const SCENARIO_FALLBACKS: Record<
  Brief['content']['scenario'],
  { headline: string; amount: string; payLabel: string; item: string; path: string }
> = {
  invoice: { headline: 'Pay Your Invoice', amount: '£480.00', payLabel: 'Pay £480.00', item: 'Invoice total', path: 'checkout' },
  deposit: { headline: 'Pay Your Deposit', amount: '£150.00', payLabel: 'Pay Deposit', item: 'Booking deposit', path: 'deposit' },
  membership: { headline: 'Start Your Membership', amount: '£29.00', payLabel: 'Start Membership', item: 'Monthly membership', path: 'join' },
  booking: { headline: 'Confirm Your Booking', amount: '£95.00', payLabel: 'Confirm Booking', item: 'Booking fee', path: 'book' },
  order: { headline: 'Complete Your Order', amount: '£64.00', payLabel: 'Pay £64.00', item: 'Order total', path: 'checkout' },
};

// ---- string sanitisers --------------------------------------------------------

const BANNED = /\b(FCA|PCI(\s|-)?DSS?|regulated|authori[sz]ed|guaranteed?|FSCS)\b/i;

/** Clamp + de-junk one model string. Returns null when unusable. */
function cleanStr(v: unknown, max: number): string | null {
  if (typeof v !== 'string') return null;
  let s = v
    .replace(/[\u0000-\u001f\u007f<>]/g, " ")
    .replace(/(https?:\/\/|www\.)\S+/gi, '')
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
    .replace(/!/g, '.')
    .replace(/\s+/g, ' ')
    .trim();
  if (!s) return null;
  if (BANNED.test(s)) return null; // compliance scrub — field falls back, never ships
  if (s.length > max) s = s.slice(0, max).replace(/\s+\S*$/, '').trim();
  return s || null;
}

function cleanEnum<T extends string>(v: unknown, allowed: readonly T[], dflt: T): T {
  return typeof v === 'string' && (allowed as readonly string[]).includes(v) ? (v as T) : dflt;
}

function cleanHex(v: unknown): string | null {
  return isHex(v) ? v.toLowerCase() : null;
}

const AMOUNT_RE = /^£\d{1,3}(,\d{3})*\.\d{2}$/;

function parseAmount(v: unknown): number | null {
  if (typeof v !== 'string' || !AMOUNT_RE.test(v.trim())) return null;
  const n = Number(v.trim().replace(/[£,]/g, ''));
  return Number.isFinite(n) && n > 0 && n <= 99_999.99 ? n : null;
}

function formatAmount(n: number): string {
  return '£' + n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function cleanPhone(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const s = v.trim();
  return /^[+()0-9 .\-]{7,24}$/.test(s) ? s : null;
}

// ---- token engine ---------------------------------------------------------------
// ONE set of brand seeds → BOTH renditions, by fixed formulas. This is what keeps
// the accent identical across modes, the neutrals consistent between retries, and
// the guard rails deterministic (no per-mode model hexes to drift).

const rgba = (hex: string, alpha: number): string => {
  const c = hex.replace('#', '');
  const r = parseInt(c.slice(0, 2), 16);
  const g = parseInt(c.slice(2, 4), 16);
  const b = parseInt(c.slice(4, 6), 16);
  return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
};

/** Nudge a colour toward legibility on a surface until it clears `min`. */
function guardOn(colour: string, surface: string, min: number): string {
  let out = colour;
  let tries = 0;
  while (contrastRatio(out, surface) < min && tries < 6) {
    out = mixHex(out, onColour(surface), 0.22);
    tries += 1;
  }
  return out;
}

export function deriveTokens(design: Brief['design'], theme: 'light' | 'dark'): ThemeTokens {
  const { primary, pageStyle, headerStyle } = design;
  const accent = design.accent || primary;

  if (theme === 'light') {
    // The tint derives from the ACCENT — it carries the brand's warmth (gold →
    // cream); a primary-derived tint reads as generic cool grey.
    const page = pageStyle === 'tinted' ? mixHex(accent, '#ffffff', 0.93) : '#ffffff';
    const surface = '#ffffff';
    const header = headerStyle === 'brand' ? primary : '#ffffff';
    const ink = relLum(primary) <= 0.35 ? primary : mixHex(primary, '#0f172a', 0.6);
    const action = guardOn(primary, surface, 2.5);
    const accent2 = guardOn(accent, surface, 1.6);
    const stripBg = relLum(primary) <= 0.25 ? primary : mixHex(primary, '#05070c', 0.65);
    return {
      page,
      header,
      onHeader: onColour(header),
      surface,
      ink,
      muted: rgba(ink, 0.62),
      line: rgba(ink, 0.16),
      action,
      onAction: onColour(action),
      accent2,
      stripBg,
      onStrip: 'rgba(255, 255, 255, 0.78)',
      stripIc: relLum(accent) >= 0.12 ? accent : 'rgba(255, 255, 255, 0.6)',
      noteBg: mixHex(accent2, page, 0.88),
      noteBorder: mixHex(accent2, page, 0.68),
    };
  }

  // Dark rendition: a deep shade of the brand primary, never plain black.
  const page = mixHex(primary, '#05070c', 0.68);
  const surface = mixHex(page, '#ffffff', 0.07);
  const header = headerStyle === 'brand' ? mixHex(primary, '#05070c', 0.55) : mixHex(page, '#ffffff', 0.04);
  const ink = mixHex('#ffffff', primary, 0.08);
  // The accent takes over as the action colour where it reads; a too-dark
  // primary is lightened instead (the Lockdales navy→gold judgement, encoded).
  const action =
    contrastRatio(accent, surface) >= 2.5 ? accent : guardOn(mixHex(primary, '#ffffff', 0.35), surface, 2.5);
  const accent2 = guardOn(accent, surface, 1.8);
  return {
    page,
    header,
    onHeader: onColour(header),
    surface,
    ink,
    muted: rgba(ink, 0.62),
    line: rgba(ink, 0.16),
    action,
    onAction: onColour(action),
    accent2,
    stripBg: mixHex(primary, '#05070c', 0.9),
    onStrip: 'rgba(255, 255, 255, 0.78)',
    stripIc: accent2,
    noteBg: mixHex(accent2, page, 0.86),
    noteBorder: mixHex(accent2, page, 0.62),
  };
}

/**
 * Per-theme logo choice. Brandfetch `theme` = the ARTWORK's colour: dark marks
 * for light headers, light marks for dark headers. When only the wrong variant
 * exists, back it with a contrasting chip (like real sites do) instead of
 * dropping straight to a monogram; no logo at all → monogram (src null).
 */
export function deriveLogo(
  tokens: ThemeTokens,
  brand: { logoUrl: string | null; logoDarkUrl: string | null },
): LogoToken {
  const headerIsLight = relLum(tokens.header) > 0.42;
  const wanted = headerIsLight ? brand.logoUrl : brand.logoDarkUrl;
  if (wanted) return { src: wanted, chip: null };
  const other = headerIsLight ? brand.logoDarkUrl : brand.logoUrl;
  if (other) return { src: other, chip: headerIsLight ? tokens.stripBg : '#ffffff' };
  return { src: null, chip: null };
}

// ---- validateSpec ---------------------------------------------------------------

export function validateSpec(
  raw: unknown,
  ctx: { name: string; colors: BrandColour[]; font: string | null },
): Brief | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const r = raw as Record<string, any>;
  const accentFallback = pickColour(ctx.colors) || '#0f766e';

  // Brand seeds. The primary anchors BOTH renditions, so it must be a colour
  // with structural weight — a too-light pick is pulled toward ink.
  const darkest = (ctx.colors || [])
    .filter((c) => isHex(c?.hex))
    .map((c) => c.hex)
    .sort((a, b) => relLum(a) - relLum(b))[0];
  let primary = cleanHex(r.design?.primary) || (darkest && relLum(darkest) <= 0.4 ? darkest : accentFallback);
  let tries = 0;
  while (relLum(primary) > 0.5 && tries < 4) {
    primary = mixHex(primary, '#0f172a', 0.35);
    tries += 1;
  }
  const design: Brief['design'] = {
    primary,
    accent: cleanHex(r.design?.accent),
    pageStyle: cleanEnum(r.design?.pageStyle, ['paper', 'tinted'] as const, 'paper'),
    headerStyle: cleanEnum(r.design?.headerStyle, ['paper', 'brand'] as const, 'paper'),
    preferred: cleanEnum(r.design?.preferred, ['light', 'dark'] as const, 'light'),
  };

  const desktop: Brief['desktop'] = {
    layout: cleanEnum(r.desktop?.layout, ['split', 'centered'] as const, 'centered'),
    summarySide: cleanEnum(r.desktop?.summarySide, ['left', 'right'] as const, 'left'),
  };

  let display = cleanEnum(r.style?.display, ['serif', 'sans', 'brand'] as const, 'sans');
  if (display === 'brand' && !ctx.font) display = 'sans';
  const style: Brief['style'] = {
    display,
    wordmarkCase: cleanEnum(r.style?.wordmarkCase, ['normal', 'upper'] as const, 'normal'),
    radius: cleanEnum(r.style?.radius, ['sharp', 'soft', 'round'] as const, 'soft'),
    density: cleanEnum(r.style?.density, ['compact', 'regular'] as const, 'regular'),
  };

  const nav = Array.isArray(r.header?.nav)
    ? r.header.nav.map((n: unknown) => cleanStr(n, 14)).filter(Boolean).slice(0, 3) as string[]
    : [];
  const header: Brief['header'] = {
    tagline: cleanStr(r.header?.tagline, 40) || '',
    nav,
    verified: r.header?.verified === true,
  };

  const stepLabels = Array.isArray(r.sections?.stepLabels)
    ? (r.sections.stepLabels.map((s: unknown) => cleanStr(s, 16)).filter(Boolean) as string[])
    : [];
  while (stepLabels.length < 3) stepLabels.push(['Your Details', 'Payment', 'Confirmation'][stepLabels.length]);
  const sections: Brief['sections'] = {
    utilityStrip: r.sections?.utilityStrip !== false,
    phone: cleanPhone(r.sections?.phone),
    banner: r.sections?.banner === true,
    steps: r.sections?.steps !== false,
    stepLabels: stepLabels.slice(0, 3),
    summary: r.sections?.summary !== false,
    altPayment: cleanEnum(r.sections?.altPayment, ['bacs', 'none'] as const, 'none'),
    referenceNote: r.sections?.referenceNote === true,
    footer: r.sections?.footer !== false,
  };

  const scenario = cleanEnum(
    r.content?.scenario,
    ['invoice', 'deposit', 'membership', 'booking', 'order'] as const,
    'invoice',
  );
  const fb = SCENARIO_FALLBACKS[scenario];

  const rawItems = Array.isArray(r.content?.lineItems) ? r.content.lineItems.slice(0, 4) : [];
  let lineItems: LineItem[] = [];
  for (const it of rawItems) {
    const label = cleanStr(it?.label, 36);
    const n = parseAmount(it?.amount);
    if (label && n !== null) lineItems.push({ label, amount: formatAmount(n) });
  }
  if (!lineItems.length) lineItems = [{ label: fb.item, amount: fb.amount }];
  // The total is ours, not the model's — recomputed so the page always adds up.
  const total = formatAmount(
    lineItems.reduce((sum, it) => sum + Number(it.amount.replace(/[£,]/g, '')), 0),
  );

  const content: Brief['content'] = {
    scenario,
    headline: cleanStr(r.content?.headline, 42) || fb.headline,
    subcopy: cleanStr(r.content?.subcopy, 110) || '',
    reference: cleanStr(r.content?.reference, 16) || '',
    lineItems,
    total,
    payLabel: cleanStr(r.content?.payLabel, 24) || 'Pay ' + total,
    methodTitle: cleanStr(r.content?.methodTitle, 34) || 'Pay by Bank Transfer (BACS)',
    methodNote: cleanStr(r.content?.methodNote, 40) || 'No fees — preferred payment method',
    referenceNoteText:
      cleanStr(r.content?.referenceNoteText, 140) ||
      'Please include your name and reference so we can match your payment.',
    reassurance: cleanStr(r.content?.reassurance, 90) || 'A receipt is emailed to you automatically.',
    footerLine: cleanStr(r.content?.footerLine, 90) || ctx.name,
  };

  return { rationale: cleanStr(r.rationale, 120) || '', design, desktop, style, header, sections, content };
}

/** Pull the first JSON object out of a model response (fences tolerated). */
export function parseBrief(text: string): unknown | null {
  const match = String(text || '').match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    return JSON.parse(match[0]);
  } catch {
    return null;
  }
}

// ---- JSON schema (Anthropic structured outputs) ---------------------------------
// Length clamps stay in validateSpec — the schema only pins shape and enums.

const str = { type: 'string' };
const strOrNull = { type: ['string', 'null'] };
const bool = { type: 'boolean' };
const obj = (properties: Record<string, unknown>, required: string[]) => ({
  type: 'object',
  properties,
  required,
  additionalProperties: false,
});

export const BRIEF_JSON_SCHEMA = obj(
  {
    rationale: str,
    design: obj(
      {
        primary: str,
        accent: strOrNull,
        pageStyle: { type: 'string', enum: ['paper', 'tinted'] },
        headerStyle: { type: 'string', enum: ['paper', 'brand'] },
        preferred: { type: 'string', enum: ['light', 'dark'] },
      },
      ['primary', 'accent', 'pageStyle', 'headerStyle', 'preferred'],
    ),
    desktop: obj(
      {
        layout: { type: 'string', enum: ['split', 'centered'] },
        summarySide: { type: 'string', enum: ['left', 'right'] },
      },
      ['layout', 'summarySide'],
    ),
    style: obj(
      {
        display: { type: 'string', enum: ['serif', 'sans', 'brand'] },
        wordmarkCase: { type: 'string', enum: ['normal', 'upper'] },
        radius: { type: 'string', enum: ['sharp', 'soft', 'round'] },
        density: { type: 'string', enum: ['compact', 'regular'] },
      },
      ['display', 'wordmarkCase', 'radius', 'density'],
    ),
    header: obj(
      { tagline: str, nav: { type: 'array', items: str }, verified: bool },
      ['tagline', 'nav', 'verified'],
    ),
    sections: obj(
      {
        utilityStrip: bool,
        phone: strOrNull,
        banner: bool,
        steps: bool,
        stepLabels: { type: 'array', items: str },
        summary: bool,
        altPayment: { type: 'string', enum: ['bacs', 'none'] },
        referenceNote: bool,
        footer: bool,
      },
      ['utilityStrip', 'phone', 'banner', 'steps', 'stepLabels', 'summary', 'altPayment', 'referenceNote', 'footer'],
    ),
    content: obj(
      {
        scenario: { type: 'string', enum: ['invoice', 'deposit', 'membership', 'booking', 'order'] },
        headline: str,
        subcopy: str,
        reference: str,
        lineItems: {
          type: 'array',
          items: obj({ label: str, amount: str }, ['label', 'amount']),
        },
        total: str,
        payLabel: str,
        methodTitle: str,
        methodNote: str,
        referenceNoteText: str,
        reassurance: str,
        footerLine: str,
      },
      [
        'scenario', 'headline', 'subcopy', 'reference', 'lineItems', 'total', 'payLabel',
        'methodTitle', 'methodNote', 'referenceNoteText', 'reassurance', 'footerLine',
      ],
    ),
  },
  ['rationale', 'design', 'desktop', 'style', 'header', 'sections', 'content'],
);

// ---- prompts -------------------------------------------------------------------

const FIELD_GUIDE = `{
  "rationale": "one line of design intent (<=120 chars)",
  "design": {                                  // brand SEEDS — light and dark renditions are DERIVED from these automatically
    "primary": "#rrggbb                       // the brand's structural colour: headers, buttons, ink, the dark rendition's world",
    "accent": "#rrggbb or null                // the brand's highlight colour (gold, coral…); null = derived from primary",
    "pageStyle": "paper | tinted              // light rendition page: pure white vs a soft brand-tinted wash (e.g. cream)",
    "headerStyle": "paper | brand             // white header with dark wordmark vs a primary-coloured header band",
    "preferred": "light | dark                // the rendition matching their REAL site"
  },
  "desktop": {
    "layout": "split | centered               // split = summary/brand pane beside the payment form; centered = one narrow column on the page",
    "summarySide": "left | right              // which side the summary pane sits on in split layout"
  },
  "style": {
    "display": "serif | sans | brand          // 'brand' uses their detected web font when available",
    "wordmarkCase": "normal | upper",
    "radius": "sharp | soft | round",
    "density": "compact | regular"
  },
  "header": { "tagline": "<=40 chars", "nav": ["<=14 chars", up to 3] , "verified": true|false },
  "sections": {
    "utilityStrip": bool, "phone": "'+44 …' or null",
    "banner": bool                            // brand banner image strip under the header
    ,"steps": bool, "stepLabels": [3 x "<=16 chars"],
    "summary": bool                           // order/invoice line-item block
    ,"altPayment": "bacs | none", "referenceNote": bool, "footer": bool
  },
  "content": {
    "scenario": "invoice | deposit | membership | booking | order",
    "headline": "<=42 chars, Title Case", "subcopy": "<=110 chars, one calm sentence",
    "reference": "<=16 chars, e.g. 'INV-2417'",
    "lineItems": [ up to 4 x { "label": "<=36 chars", "amount": "£1,240.00" } ],
    "total": "£… (sum of lineItems)", "payLabel": "<=24 chars",
    "methodTitle": "<=34", "methodNote": "<=40", "referenceNoteText": "<=140",
    "reassurance": "<=90", "footerLine": "<=90, brand strapline"
  }
}`;

const EXEMPLAR_INPUT = `{"name":"Lockdales","domain":"lockdales.com","description":"Suffolk's leading specialist auctioneers and dealers in jewellery, watches, coins and militaria.","industries":["Jewellery and Luxury Products"],"colors":[{"hex":"#102d42","type":"dark"},{"hex":"#ffffff","type":"light"},{"hex":"#94821b","type":"accent"}],"font":null}`;

const EXEMPLAR_OUTPUT = `{"rationale":"Heritage auction house: cream-tinted page, white header with serif upper wordmark, navy structure with gold highlights, BACS-first invoice.","design":{"primary":"#102d42","accent":"#94821b","pageStyle":"tinted","headerStyle":"paper","preferred":"light"},"desktop":{"layout":"split","summarySide":"left"},"style":{"display":"serif","wordmarkCase":"upper","radius":"soft","density":"regular"},"header":{"tagline":"Auctioneers & Valuers","nav":["Auctions","Valuations","Contact"],"verified":true},"sections":{"utilityStrip":true,"phone":"+44 (0)1473 627110","banner":false,"steps":true,"stepLabels":["Payment Method","Card Details","Confirmation"],"summary":true,"altPayment":"bacs","referenceNote":true,"footer":true},"content":{"scenario":"invoice","headline":"Pay Your Invoice","subcopy":"Settle your auction invoice by bank transfer or card.","reference":"Bidder 318","lineItems":[{"label":"Hammer price","amount":"£1,000.00"},{"label":"Buyer's premium (24%)","amount":"£240.00"}],"total":"£1,240.00","payLabel":"Pay £1,240.00","methodTitle":"Pay by Bank Transfer (BACS)","methodNote":"No fees — preferred payment method","referenceNoteText":"Please include your name and bidder number as the payment reference so we can match your payment to your invoice.","reassurance":"A receipt is emailed to you as soon as payment is received.","footerLine":"Lockdales Auctioneers & Valuers — Suffolk"}}`;

export const DESIGN_SYSTEM = [
  'You are a senior brand designer at SettlePay, a UK studio that builds bespoke branded',
  'payment pages for small businesses. Design ONE illustrative mock payment page for the',
  'business described by the user, convincing enough that its owner would say "that looks',
  'like OUR site".',
  '',
  'You may be shown up to three images: a screenshot of their homepage, their brand banner,',
  'and their logo. Derive the palette, mood and typography feel from what you SEE — match',
  'their actual site, not generic defaults. Without images, work from the colour list and',
  'description.',
  '',
  'Return ONLY a JSON object in exactly this shape (no markdown fences, no commentary):',
  FIELD_GUIDE,
  '',
  'Design guidance:',
  '- Prefer colours from the brand’s real world; you may use hexes you observe in the',
  '  images, not only the listed ones.',
  '- You choose brand SEEDS, not palettes: "primary" is the brand’s structural colour,',
  '  "accent" its highlight. A design-token system derives the full light AND dark',
  '  renditions from them deterministically (the exemplar’s navy primary + gold accent',
  '  yields a cream light page and a navy-shaded dark page with gold actions). Set',
  '  "preferred" to whichever rendition matches their real site.',
  '- Desktop layout: "split" (summary/brand pane beside the form, like modern hosted',
  '  checkouts) suits businesses with itemised orders; "centered" suits simple single',
  '  payments. Choose what this business would ship.',
  '- Choose the sections a business like this would actually have: an auction house wants an',
  '  invoice summary, BACS panel and a payment-reference note; a gym wants a simple membership',
  '  start; a trades business wants a deposit with a booking reference.',
  '- Line items must feel authentic to the industry, with realistic amounts between £20 and',
  '  £5,000. Amounts are strings like "£1,240.00" and the total must equal their sum.',
  '- UK English. Headline in Title Case. Calm, confident microcopy — no hype.',
  '',
  'HARD RULES — never break:',
  '- Never claim the business or SettlePay is "FCA authorised", "FCA regulated",',
  '  "PCI compliant" or "PCI DSS compliant". No "FSCS", no "guaranteed".',
  '- Never invent statistics, testimonials, awards or client relationships. Line items are',
  '  plausible generic examples, never real product names presented as real prices.',
  '- No emoji. No exclamation marks. No URLs in any string.',
  '',
  'Worked example — fidelity and format bar only, NOT a house style:',
  'Input brand: ' + EXEMPLAR_INPUT,
  'Output: ' + EXEMPLAR_OUTPUT,
  'Derive THIS brand’s palette, mood, typography and content from its own assets — do not',
  'copy the example’s navy, gold, serif or auction content.',
].join('\n');

export function briefUserPrompt(b: {
  name: string;
  domain: string;
  description: string;
  industries: string[];
  colors: BrandColour[];
  font: string | null;
  markdown: string | null;
  imageNote: string;
}): string {
  const parts = [
    'Design the payment page for this business.',
    'Brand: ' +
      JSON.stringify({
        name: b.name,
        domain: b.domain,
        description: b.description || 'unknown',
        industries: b.industries,
        colors: b.colors,
        font: b.font,
      }),
  ];
  if (b.markdown) parts.push('Excerpt of their homepage copy:\n' + b.markdown);
  if (b.imageNote) parts.push(b.imageNote);
  return parts.join('\n\n');
}
