# SettlePay — Design System

**The single source of truth for SettlePay's brand, visual language and UI.**
If you are an agent or developer building anything SettlePay-branded, read this first, then
[`COMPONENTS.md`](./COMPONENTS.md) for the component catalogue. Match these rules exactly — do not
invent new colours, radii, fonts or spacing.

- **Live token definitions:** [`src/styles/styles.css`](../src/styles/styles.css) (`:root`)
- **Component styles:** `styles.css` + [`kit-extras.css`](../src/styles/kit-extras.css) + [`site.css`](../src/styles/site.css)
- **Brand facts & nav/footer/SEO config:** [`src/data/site.mjs`](../src/data/site.mjs)

---

## 1. What SettlePay is (positioning)

> SettlePay gives traditional UK businesses a modern, **branded** way to get paid online — without
> chasing bank transfers, cheques or phone payments. Customers check out on a page that looks like
> the client's own business, while payments run securely through trusted, **FCA-regulated processors**
> (Stripe, Adyen, Checkout.com, GoCardless) behind the scenes.
> **No lock-in. No holding the client's money. No looking like everyone else.**

It is a **bespoke payment-page development & integration service**, not a payments licence-holder.

**Audience:** sceptical, reputation-conscious **45–65+ UK business owners** (auctioneers, estate &
lettings agents, timber merchants, sole traders, SMEs). Every decision optimises for **perceived
trustworthiness and calm competence before persuasion**.

---

## 2. Legal identity & compliance — LOAD-BEARING (never break these)

These are conduct/legal requirements, not style preferences. Breaking them is a real risk.

- **SettlePay is a trading name of Finlay Salisbury, a sole trader.** NOT a limited company. **Never**
  write "Ltd"/"Limited", a company number, "registered in England & Wales", or imply incorporation.
  Correct disclosure: *"SettlePay is a trading name of Finlay Salisbury."*
- **Never claim SettlePay is "FCA authorised" or "FCA regulated."** Correct: *"payments are processed
  by FCA-regulated partners / processors."*
- **Never claim SettlePay is "PCI DSS compliant."** Correct: *"PCI DSS compliance is handled by your
  chosen processor; a hosted payment page typically reduces your PCI scope (often to SAQ A); you
  complete your own self-assessment."*
- **Never show an FSCS badge** or imply FSCS protection (payment firms aren't covered).
- **Never** use "Powered by [processor]" partnership-implying language, fake urgency, countdowns, or
  fabricated statistics/metrics/case studies.
- **SettlePay never holds, touches or controls funds** — money settles directly from the PSP to the
  client's own bank account. State this openly; it's a trust feature.
- **Real vs illustrative:** *Lockdales Auctioneers* is the only real, live client (badge it
  "Live client"). Any other example (e.g. *Harbourside Lettings*) must be labelled "Illustrative
  example" with a disclaimer.

---

## 3. Voice & content

- Plain, honest, calm, jargon-light **UK English** (organise, reconcile, personalise, licence/license).
- **"you / your"** = the reader; **"we / our"** = SettlePay. Solo founder — avoid "our team".
- **Title Case** for headlines & buttons ("Enquire Now", "See How It Works"). Sentence case for body.
  Eyebrow/badge labels are **UPPERCASE** with letter-spacing (one deliberate sentence-case variant:
  "See the impact").
- **No emoji, ever.** Iconography does the visual lifting.
- Concrete over vague; anchor on the pain of the status quo (chasing transfers, manual reconciliation)
  before the benefit. No hype.
- Headline pattern: a plain phrase with **one blue-highlighted word/phrase** — e.g. "We Build the
  Bridge to **Effortless Payments**", "The Plumbing, **Explained**". Implement the blue word as
  `<span>` inside the heading (see `SectionHeader`).
- Recurring motifs: "bespoke", "branded", "the plumbing", "The Front Door / The Engine Room / The
  Bookkeeper", "reconciliation", "settle".

---

## 4. Colour — the ~60/30/10 rule

The single most important visual discipline.

| Token | Value | Role |
|---|---|---|
| `--color-primary-brand` | `#0F172A` | **Navy** — authority surfaces (nav-trust strips, CTA band, footer, highlighted ROI card) and body text. ~30%. |
| `--color-primary-action` | `#3B82F6` | **Blue** — RESERVED for the single primary action & key interactive affordances. ~≤10%. |
| `--color-primary-action-hover` | `#2563EB` | Blue pressed/hover. |
| `--color-secondary-bg` | `#F1F5F9` | Light slate — calm fills/sections. Part of the ~60% neutral field. |
| `--color-pure-white` | `#FFFFFF` | Base canvas. Part of the ~60%. |

**Functional colours — icon tints & status badges ONLY, never decoration:**

| Token | Value | Use |
|---|---|---|
| `--color-success` | `#10B981` | succeeded / synced / "Live" / matched |
| `--color-warning` | `#F59E0B` | attention / pending (amber category tiles) |
| `--color-info` | `#8B5CF6` | violet category accent (sparingly) |
| `--color-error` | `#DC2626` | errors (always pair with icon + text) |

**Rules:**
- **~60% neutral/white, ~30% navy, ~≤10% blue.**
- **Blue is never decorative.** It marks the one primary action, the highlighted headline word, focus
  rings, active states, step numbers, link underlines. Exactly **one** filled-blue primary button and
  **one** outline secondary per view — never two equally-weighted blue buttons.
- Functional colours appear only as low-saturation tints behind icons or as small status badges.

---

## 5. Typography

- **Family:** `--font-primary` = **Satoshi** (humanist geometric sans), loaded via Fontshare CDN in
  `BaseHead.astro` (weights 400/500/600/700). System-ui fallback. `--font-mono` for code only.
- **Body biased upward for ageing eyes:** fluid base **16→18px** (`--text-base`), line-height
  **1.6–1.75**, measure **~50–75ch**, left-aligned long copy (never justified/centred). **No thin/light
  weights for body.**

| Role | Size | Notes |
|---|---|---|
| Display / hero H1 | `clamp(2.25rem, 3.5vw + 1rem, 3.75rem)` | 700, line-height 1.05, tracking −0.035em |
| Section title (H2) | `clamp(1.75rem, 2.5vw + 0.5rem, 2.75rem)` | 700, tracking −0.03em, one blue `<span>` |
| Card / feature title | 1.35rem | 700 |
| Step / sub-title (H3) | 1.15rem | 700 |
| Lead / hero sub | 1.1rem | line-height 1.7, opacity ~0.6 |
| Body | 1rem–1.05rem | line-height 1.6–1.75 |
| Eyebrow / badge / label | 0.75rem | 600, uppercase, letter-spacing 0.04em |
| Micro (timestamps) | 0.7rem | never for reading copy |

---

## 6. Spacing & layout

- **Generous spacing is a trust signal.** Section vertical padding **6rem** (`.section-pad`; 4rem mobile).
- **Container:** `max-width: 1200px`, gutters 1.5rem (`.container`).
- **Layout patterns:** sticky floating-island nav (top 12px, max-width 940px, centred); hero is a
  2-col grid (copy left / mockup right), collapses to 1 col under 960px; value props alternate
  left/right ("zig-zag"); trust signals in a single elevated white bar.
- Anchor scroll offset of 90px (`:target`) clears the floating nav.

---

## 7. Corner radii (the formalised scale)

| Token | Value | Applies to |
|---|---|---|
| `--radius-button` | **100px** (pill) | primary/secondary buttons, nav island, badges, chips, tags, the skip link |
| `--radius-input` | **8px** | form inputs & small controls |
| `--radius-card` | **24px** | cards, panels, modal, calculator inputs box, TOC |
| `--radius-icon` | **12px** | icon tiles (12–14px range acceptable) |
| — (literal) | **16px** | "soft cards": ROI result cards, FAQ items |

> ⚠️ Buttons are **pills (100px)**, fields are **8px** — do not reuse `--radius-button` for inputs.
> The hero checkout mockup intentionally uses its own 4–8px (Shopify-style) language; keep it separate.

---

## 8. Elevation (shadows)

Soft, low-spread, **blue-tinted** (`rgba(30,58,138,…)`) — never harsh black, never neumorphism.

| Token | Use |
|---|---|
| `--shadow-sm` | subtle lift |
| `--shadow-md` | cards (default), open FAQ items |
| `--shadow-lg` | mockups, prominent cards |
| `--shadow-cta` / `--shadow-cta-hover` | the primary CTA's blue glow only |

Signature **"bezel-wrap"** (`.bezel-wrap`): a 6px padded outer frame with a faint inset hairline,
radius 6px larger than the card — frames the hero checkout & dashboard mockups like devices.

**Borders/lines:** hairlines `rgba(15,23,42,.06)`; control borders `rgba(15,23,42,.12)`; on dark
`rgba(255,255,255,.08–.20)`.

---

## 9. Motion

Minimal, brief, eased, **reduced-motion-aware**. Two easings only:
- `--ease-snappy` `0.15s cubic-bezier(.4,0,.2,1)` — micro-feedback (hover/press).
- `--ease-cinematic` `0.6s cubic-bezier(.22,1,.36,1)` — reveals, card hover lift.

Hover/press: primary button → darker blue + `translateY(-1px)` + larger glow; press → `scale(.98)`.
Cards → `translateY(-4px)` + deeper shadow. Nav links → 2px blue underline grows from left.
**No** carousels, parallax, scroll-jacking or attention-grabbing hero animation. Honour
`prefers-reduced-motion` (disable transforms/transitions).

---

## 10. Iconography

- **System:** **Heroicons v2 (outline)**, MIT-licensed. 24×24, `fill="none"`,
  `stroke="currentColor"`, round caps/joins. Stroke-width **1.5** for decorative/feature tiles, **2–2.5**
  for inline UI (arrows, mail, checks).
- **Always** render via [`Icon.astro`](../src/components/Icon.astro) (`<Icon name="…" sw={…} />`). Add new
  glyphs to its path map (copy the exact Heroicons outline path) — don't inline ad-hoc SVGs.
- Icons inherit colour via `currentColor`; tint by context (blue accent tiles; green/amber/violet
  category tiles; white on dark).
- **No emoji. No Unicode glyphs as icons.**

---

## 11. Logos & brand assets

In [`public/assets/logos/`](../public/assets/logos/). Pick by background:

| File | Use |
|---|---|
| `wordmark-light.svg` | **Navy** wordmark for **light** backgrounds → the nav (height 42px). Near-square (~0.94). |
| `wordmark-dark.png` / `settlepay-darkmode.png` | **White** wordmark for **dark** backgrounds (used to build the OG image). |
| `wordmark-squircle.svg` | Wordmark in a navy rounded-square — footer logo. |
| `monogram.svg` | Navy squircle "SP" mark — favicon & app icons. |
| `lockdales-coin.png` | Lockdales client asset (use only for the real client). |

The logo's "P" embeds a credit-card glyph (chip + magstripe) — a brand signature, not a reusable icon.
**Never recolour brand marks** beyond the supplied light/dark variants.

---

## 12. Payment marks

In [`public/assets/payment/`](../public/assets/payment/): `Visa.svg`, `Mastercard.svg`, `Amex.svg`,
`Klarna.svg`, `apple-logo.svg`, `google-g.svg`. **Display as-is — never recolour.** Apple Pay / Google
Pay render as proper branded buttons (black Apple-glyph button; white button with the four-colour
Google "G"). Used inside the hero checkout mockup only.

---

## 13. Imagery

Authentic product-in-situ over stock. The system ships **bespoke CSS/SVG UI mockups** (branded
checkout, reconciliation dashboard) rather than photography. If adding photos: real sector imagery
(auction house, estate agent, timber merchant), calm/clean/cool-neutral. **No** clichéd
handshake/skyline/headset-model stock, **no** AI-obvious imagery. Use placeholder slots and ask the
user for real assets.

---

## 14. Components

Built as Astro components; each has a set design. Full catalogue, props and "use when" guidance in
[`COMPONENTS.md`](./COMPONENTS.md). Summary:

- **Primitives:** `Button`, `Icon`, `SectionHeader`, `Breadcrumbs`.
- **Chrome:** `Nav`, `Footer`, `EnquireModal`, `BaseHead` (SEO), `SiteScripts` (behaviour).
- **Layouts:** `BaseLayout`, `ContentLayout` (About-style markdown), `LegalLayout` (legal markdown + TOC).
- **Sections** (`src/components/sections/`): `Hero`, `ValueProps`, `HowItWorks`, `FastStart`, `UseCases`,
  `TrustBar`, `Calculator`, `CtaBand`.
- **Mockups** (`src/components/previews/`): `Chrome`, `DashPreview`, `Dashboard`, `CheckoutTemplate`,
  `ReconcileTemplate`, `OnboardTemplate`.

**Rule:** reuse these. Don't hand-roll a button, icon, or section header — use the component so the
design stays consistent and centrally controllable.

---

## 15. SEO (built in — keep it that way)

Static HTML (Astro) so all content is crawlable. Every page: unique `<title>`, meta description,
canonical, Open Graph + Twitter card, theme colour, favicons, manifest. JSON-LD via
[`structuredData.mjs`](../src/data/structuredData.mjs) (Organization + WebSite on home; WebPage +
BreadcrumbList on inner pages; FAQPage on `/faq/`). `sitemap-index.xml` auto-generated; `robots.txt`
points to it. Per-page copy lives in [`src/data/content/seo.json`](../src/data/content/seo.json).
Keep claims honest (no "FCA authorised" in titles/descriptions).

---

## 16. Quick compliance checklist (before shipping anything)

- [ ] No "Ltd" / company number / "registered in England & Wales".
- [ ] No "FCA authorised/regulated" or "PCI DSS compliant" claims about SettlePay.
- [ ] No FSCS badge, no "Powered by", no fake urgency, no invented metrics.
- [ ] "We never hold your money" stated where relevant.
- [ ] Real vs illustrative clients labelled correctly.
- [ ] UK English, Title Case headings, no emoji, one primary + one secondary button per view.
- [ ] Blue used only for the primary action / accents — never decoration.
- [ ] New icons via `Icon.astro`; new buttons/headers via their components.
