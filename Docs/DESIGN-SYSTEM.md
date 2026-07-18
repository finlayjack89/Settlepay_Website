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
- **Title Case** for headlines & buttons ("Send an Enquiry", "See How It Works"). Sentence case for body.
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

| Role | Token / size | Notes |
|---|---|---|
| Display / hero H1 | `--text-display` = `clamp(2.1rem, 3.2vw + 1rem, 3.6rem)` | 700, line-height 1.05, tracking −0.035em |
| Section title (H2) | `--text-title` = `clamp(1.65rem, 2vw + 0.75rem, 2.4rem)` | 700, tracking −0.03em, one blue `<span>` |
| Interior page H1 | `--text-page-title` = `clamp(1.9rem, 2.2vw + 1rem, 2.6rem)` | 700, `.page-header__title` |
| Card / feature title | `--text-card` = 1.35rem | 700 |
| Step / sub-title (H3) | `--text-step` = 1.15rem | 700 |
| Lead / hero sub | `--text-lead` = 1.1rem | line-height 1.7, opacity ~0.6 |
| Body | `--text-body` = 1rem (dense UI: `--text-sm` 0.9rem) | line-height 1.6–1.75 |
| Eyebrow / badge / label | `--text-label` = 0.75rem | 600, uppercase, letter-spacing 0.04em |
| Micro (timestamps) | `--text-micro` = 0.7rem | never for reading copy |

Weights (`--weight-regular/medium/semibold/bold`), line heights (`--leading-tight/snug/normal/relaxed`),
tracking (`--tracking-display/heading/eyebrow`) and the reading measure (`--measure` = 62ch) are all
tokens — use them, not fresh literals.

---

## 6. Spacing & layout

- **Spacing tokens:** `--space-section` = `clamp(3.5rem, 2.75rem + 2.5vw, 4.75rem)` (`.section-pad`),
  `--space-section-compact` = `clamp(2.25rem, 2rem + 1.25vw, 3rem)` (slim bands: trust strip,
  mini-cta), `--space-header-gap` = 2.5rem (SectionHeader → content), plus the general scale
  `--space-1`–`--space-8` (0.25–3rem). Clamps cover mobile — no per-breakpoint padding overrides.
- **Rhythm comes from alternating surfaces, not padding — the light/dark rhythm.** Homepage bands
  alternate white / slate (`--color-secondary-bg`), punctuated by deliberate navy **"dark chapters"**
  that make product evidence glow: the hero's contained `.stage-dark` panel (checkout mockup +
  particle field), CardMoment (the payment-card product shot), the one full-bleed `.section--dark`
  chapter (radial `#1E2B45` glow over navy — **at most once between the hero and the CtaBand; dark
  stays special**), and the closing CtaBand + footer. A section *earns* a navy stage when it presents
  product evidence or the final ask — never for variety. On dark, use the on-dark ramp
  (`--color-on-dark-*`, `--color-text-on-dark-muted`); keep WCAG AA contrast.
- A **whisper-quiet fractal-noise overlay** sits over the whole page at 2.8% opacity (fixed,
  `pointer-events: none`) — paper-grain tactility without visible pattern.
- **Container:** `max-width: var(--container)` (1200px), gutters 1.5rem (`.container`).
- **Layout patterns:** sticky floating-island nav (top 12px, max-width 940px, centred); hero is a
  2-col grid (copy left / dark product stage right), collapses to 1 col under 960px; value props are
  a 2×2 bento of white cards with top-cropped mockup media; trust signals in a slim one-line strip
  under the hero.
- Anchor scroll offset of 86px (`--nav-offset` via `scroll-padding-top`) clears the floating nav.

---

## 7. Corner radii (the formalised scale)

| Token | Value | Applies to |
|---|---|---|
| `--radius-button` | **100px** (pill) | primary/secondary buttons, nav island, badges, chips, tags, the skip link |
| `--radius-input` | **8px** | form inputs & small controls |
| `--radius-card` | **24px** | cards, panels, modal, calculator inputs box, TOC |
| `--radius-icon` | **12px** | icon tiles (12–14px range acceptable) |
| `--radius-soft` | **16px** | "soft cards": ROI result cards, FAQ items, fact tiles, case-study panels |

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

**Borders/lines:** hairlines `--color-ink-06`; control borders `--color-ink-12`; on dark the
on-dark ramp (`--color-on-dark-08`–`--color-on-dark-20`). Inset hairline for bezels/nav:
`--ring-inset`.

**Frosted glass — a system, not a single moment.** Every glass surface pairs a backdrop blur
(`--blur-glass-*`) with a translucent fill and a hairline definition edge:

| Surface | Recipe |
|---|---|
| Floating-island nav pill | `blur(var(--blur-glass-nav)) saturate(var(--glass-saturate))`; white fill 0.62→0.78 with scroll; dark-glass variant `rgba(15,23,42,.5→.72)` over navy sections (`.navbar--over-dark`) |
| StickyCta (mobile action bar) | `blur(var(--blur-glass-bar)) saturate(var(--glass-saturate-soft))` |
| StatusChip (pills over dark stages) | `blur(var(--blur-glass-chip)) saturate(var(--glass-saturate))` |
| Modal overlay | `blur(var(--blur-glass-veil))` — a veil, not a frost |

Glass rules (each encodes a real incident):
1. Write `-webkit-backdrop-filter` FIRST, the standard property LAST — the CSS minifier keeps only
   the final declaration of a pair, so standard-first order ships webkit-only CSS and the frost
   silently dies in production while the dev server looks fine.
2. **Never put `overflow: hidden/clip` on an ancestor of the nav** (html/body) — it kills the
   backdrop-filter; the horizontal-overflow guard lives on `<main>`.
3. **Never add `view-transition-name` to the nav** (see §9 — it starves the backdrop).
4. Over navy, flip to the dark-glass variant — light frost reads as an opaque grey slab.

On-dark stage internals (hero stage layers 6px, FlowScene node chips 8px) are component-local
translucency, not part of the glass scale.

---

## 9. Motion — motion is evidence

The site carries a **dynamic canvas/WebGL layer** on the calm-competence base. Motion is a trust
signal here exactly when it demonstrates craft and product truth — and noise when it doesn't.
Three principles govern every moving thing:

1. **Motion is evidence, not decoration.** Every animation demonstrates something true about the
   product: payment arcs crossing the UK map, the living dashboard ticking as payments arrive, the
   card's material quality under light. **Test: what does this motion prove? If nothing, cut it.**
2. **Physics over easing tricks.** World-fixed lighting while surfaces tilt; momentum springs driven
   by scroll velocity; odometer digits that roll like hardware (forward only, least-significant
   digit settles first); frame-rate-independent lerps.
3. **Enhancement, never dependency.** The static / no-JS / reduced-motion state is a first-class
   **finished** render, never a degraded one. Markup ships the final true figure; hidden reveal
   states exist only under `html.reveal-ready`.

**Easings — curve/duration split.** Compose `--curve-*` with `--duration-*`; the bundled `--ease-*`
shorthands cover the everyday cases. Keyframes and bespoke durations reuse the curve tokens —
never paste a `cubic-bezier()` literal.

| Curve | Default duration | Use |
|---|---|---|
| `--curve-snappy` | `--duration-snappy` 0.15s | micro-feedback (hover/press) |
| `--curve-cinematic` | `--duration-cinematic` 0.6s | reveals, lifts; keyframes at bespoke durations |
| `--curve-spring` | `--duration-spring` 400ms | overshoots — nav collapse, StickyCta |

Hover/press: primary button → darker blue + `translateY(-1px)` + larger glow; press → `scale(.98)`.
Cards → `translateY(-4px)` + deeper shadow (cinematic). Nav links → 2px blue underline grows from left.

### The canvas-island contract

The four WebGL islands — [`PayCard`](../src/components/PayCard.astro), [`UKMap`](../src/components/UKMap.astro),
[`FlowScene`](../src/components/FlowScene.astro), [`ParticleField`](../src/components/ParticleField.astro) —
share one verified contract. **Any new island must obey all of it:**

- `data-gl-state="live" | "static" | "unsupported"` set on the element — testable.
- rAF **gated by IntersectionObserver** — never animate off-screen; live loops also pause when
  `document.visibilityState` is hidden.
- `devicePixelRatio` **capped at 2**.
- `prefers-reduced-motion` → render **one static rest frame**, no rAF.
- `webglcontextlost` → fall back **permanently** to the DOM face.
- The CSS/DOM fallback must be **complete before** WebGL replaces it — it is the finished render
  for no-JS/unsupported visitors, not a loading state.
- Raw WebGL, zero runtime dependencies.

### Behaviour-layer recipes ([`SiteScripts.astro`](../src/components/SiteScripts.astro))

- **Quantized scroll-progress custom properties:** JS writes one 0→1 variable (e.g.
  `--nav-scroll-p` over the first 150px) on a scroll-rAF; every morphing property is a CSS
  `calc()` off it and the springy transition smooths the steps. No per-frame layout thrash.
- **IO-driven one-shot reveals:** `[data-live]` mockups get `.is-live` at ~⅓ visibility, once.
- **`[data-reveal]` stagger:** per parent group via `--reveal-delay`, capped at 5 × 70ms.
- **Frame-rate-independent lerps:** `shown += (target − shown) × (1 − e^(−dt/τ))` — 60Hz and
  120Hz match; wheel clicks get trackpad-like momentum.
- **Shared scroll-velocity spring:** `[data-tilt-scroll]` elements lean with an under-damped spring
  chasing a shared decaying scroll velocity, settling flat at rest.
- **Scroll-scrubbed narrative (MarketShift):** tall section, sticky stage; the number chases scroll
  progress and settles on the true attributed figure (`.is-settled` reveals the sourced stats).
  Reduced motion: a static band with the real stat.

### Cross-document view transitions

MPA navigation gets a **0.18s root fade** (CSS-only `@view-transition`; reduced motion gets none;
Firefox degrades to a plain navigation). **Never add `view-transition-name` to the nav** — naming
it lifts it into its own snapshot, isolated from the root, which starves the pill's
`backdrop-filter` of a backdrop and the frosted glass silently stops rendering (see the comment
block in [`styles.css`](../src/styles/styles.css)).

### The ban list, revised

**Still banned:** auto-playing carousels; scroll-hijacking that blocks reading; fake urgency;
decorative motion with no product meaning.
**Sanctioned — under the contract above:** scroll-scrubbed narrative sections (MarketShift),
ambient WebGL layers (ParticleField), product self-demos (living dashboard, idle checkout demo),
cross-document view transitions.

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

One scoped exception: on the `PayCard` physical-card mockup the Visa wordmark renders monochrome
silver — the treatment real card faces use — because it depicts a customer's card, not a checkout
trust mark. Everywhere else the as-is rule stands.

---

## 13. Imagery

Authentic product-in-situ over stock. The system ships **bespoke CSS/SVG/WebGL product mockups**
(branded checkout, living dashboard, the payment card) rather than photography. If adding photos: real sector imagery
(auction house, estate agent, timber merchant), calm/clean/cool-neutral. **No** clichéd
handshake/skyline/headset-model stock, **no** AI-obvious imagery. Use placeholder slots and ask the
user for real assets.

---

## 14. Components

Built as Astro components; each has a set design. Full catalogue, props and "use when" guidance in
[`COMPONENTS.md`](./COMPONENTS.md). Summary:

- **Primitives:** `Button`, `Icon`, `SectionHeader`, `Breadcrumbs`, `StatusChip`.
- **Chrome:** `Nav`, `Footer`, `EnquireModal`, `StickyCta`, `BaseHead` (SEO), `SiteScripts` (behaviour).
- **Layouts:** `BaseLayout`, `ContentLayout` (About-style markdown), `LegalLayout` (legal markdown + TOC).
- **Sections** (`src/components/sections/`), in homepage order: `Hero`, `TrustBar`, `CardMoment`,
  `ValueProps`, `OurWork`, `PreviewTeaser`, `HowItWorks`, `MarketShift`, `FastStart`, `Compare`,
  `SecurityEvidence`, `Calculator`, `CtaBand`, `Sources`.
- **Canvas islands** (`src/components/`): `ParticleField`, `FlowScene`, `UKMap`, `PayCard` — WebGL
  under the §9 island contract.
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
- [ ] CTA funnel: primary = "Send an Enquiry" (modal, `SITE.cta.primary`); secondary = "Book a Free
      Call" → `/book/` (`SITE.cta.secondary`). Don't invent new funnel labels per page.
- [ ] Blue used only for the primary action / accents — never decoration.
- [ ] New icons via `Icon.astro`; new buttons/headers via their components.
- [ ] Any new motion passes the evidence test (§9): it proves something about the product.
- [ ] Reduced-motion and no-JS states are **finished renders**, not degraded ones.
- [ ] New canvas/scroll effects follow the §9 contracts (`data-gl-state`, IO-gated rAF, DPR ≤ 2).
- [ ] Tokens, not literals: curves via `--curve-*`, glass via `--blur-glass-*`, soft cards via
      `--radius-soft`, ink/on-dark alphas via their ramps.
- [ ] At most one full-bleed `.section--dark` between the hero and the CtaBand.
