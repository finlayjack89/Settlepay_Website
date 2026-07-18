# SettlePay — Component Catalogue

Every reusable building block, its props, and when to use it. **Always reuse these** rather than
hand-rolling markup, so the design stays consistent and centrally controllable. Pair with
[`DESIGN-SYSTEM.md`](./DESIGN-SYSTEM.md) for the visual rules.

All components live in `src/components/`. Import with a relative path, e.g.
`import Button from '../components/Button.astro'`.

---

## Primitives

### `Button.astro`
The only way to render a button or button-styled link. Pills (100px), one primary + one secondary per view.

| Prop | Type | Default | Notes |
|---|---|---|---|
| `variant` | `"primary" \| "secondary"` | `"primary"` | primary = filled blue; secondary = outline |
| `size` | `"large"` | — | larger primary (hero/CTA) |
| `onDark` | boolean | `false` | secondary styled for dark backgrounds |
| `icon` | Heroicon name | — | trailing icon (e.g. `"arrow"`, `"mail"`) |
| `href` | string | — | renders an `<a>`; omit for a `<button>` |
| `type` | `"button" \| "submit"` | `"button"` | for `<button>` elements; use `"submit"` inside a form |
| `enquire` | boolean | `false` | adds `data-enquire` → opens the consultation modal |
| `class` | string | — | extra classes (rare) |

```astro
<Button variant="primary" icon="arrow" enquire>{SITE.cta.primary.label}</Button>
<Button variant="secondary" href={SITE.cta.secondary.href}>{SITE.cta.secondary.label}</Button>
```
**Use when:** any call to action. For "open the enquiry form" use `enquire`; for navigation use `href`.
CTA labels come from `SITE.cta` in `src/data/site.mjs` — primary **"Send an Enquiry"** (always the
modal), secondary **"Book a Free Call"** (always `/book/`). Don't hardcode funnel labels.

### `Icon.astro`
Heroicons v2 outline, inline SVG, `currentColor`.

| Prop | Type | Default |
|---|---|---|
| `name` | string (key in the path map) | falls back to `check` |
| `sw` | number (stroke width) | `1.5` |
| `class` / `style` | — | — |

Available names: `phone, mail, clock, arrow, sparkles, cog, refresh, users, card, shield, lock, globe,
check, chevron, close, menu, store, scale, chat, banknotes`. **Add new glyphs to the `P` map in `Icon.astro`**
(copy the exact Heroicons outline path) — never inline ad-hoc SVGs. `sw` 1.5 = decorative tiles,
2–2.5 = inline UI.

### `SectionHeader.astro`
Eyebrow + title (with one optional blue highlight word) + subtitle. Used atop most sections.
Centred by default; `align="left"` for sections whose content runs header-left / content-right
(HowItWorks, Calculator).

| Prop | Type | Notes |
|---|---|---|
| `eyebrow` | string | UPPERCASE label (badge) |
| `sentence` | boolean | sentence-case eyebrow variant (e.g. "See the impact") |
| `title` | string | plain leading text |
| `blue` | string | the highlighted word/phrase (rendered blue) |
| `titleAfter` | string | text after the blue word |
| `subtitle` | string | supporting line |
| `align` | `"center" \| "left"` | default `"center"` |

```astro
<SectionHeader align="left" eyebrow="How It Works" title="The Plumbing, " blue="Explained" subtitle="…" />
```

### `StatusChip.astro`
Small glass notification chip floated over dark product stages (`.stage-dark`) — narrates an outcome
("Payment received · £850.00"). Decorative: wrap chip groups in `aria-hidden="true"`. Styles in
`kit-extras.css` (`.status-chip`).

| Prop | Type | Notes |
|---|---|---|
| `icon` | Heroicon name | rendered in a tinted 30px tile |
| `label` | string | the message |
| `value` | string | optional bold value appended after "·" |
| `tone` | `"neutral" \| "success"` | success = green tint (functional colour, never blue) |
| `class` | string | positioning classes (e.g. `hero-chip hero-chip--1`) |

### `Breadcrumbs.astro`
`items={[{ name, path }]}` — last item is the current page. Used on all inner pages (also feeds
`BreadcrumbList` JSON-LD via the layouts).

---

## Chrome (site-wide)

### `Nav.astro`
Sticky floating-island nav. Links from `SITE.nav`, primary `SITE.cta.primary.label` (opens modal),
mobile drawer (hamburger < 768px). No props. Edit links in `src/data/site.mjs`.

### `Footer.astro`
Two-column footer with the **honest sole-trader disclosure** (no "Ltd"). Links from `SITE.footerLinks`,
contact from `SITE`. No props.

### `EnquireModal.astro`
The free-consultation form (business, name, email, message + honeypot). Rendered once by `BaseLayout`;
opened by any `[data-enquire]` button. Submits to `SITE.formEndpoint` if set, else a mailto fallback.
No props.

### `StickyCta.astro`
Mobile-only frosted action bar (glass: `--blur-glass-bar` + `--glass-saturate-soft`) carrying the
primary ask. Shown/hidden by `SiteScripts` via IO: slides in (`--curve-spring`) once the hero
scrolls away, hides whenever the CTA band or footer is on screen so it never doubles the real
button. Homepage only. No props.

### `BaseHead.astro`
All `<head>` SEO. Driven by props from the page/layout.

| Prop | Notes |
|---|---|
| `title`, `description`, `keywords` | meta basics |
| `ogTitle`, `ogDescription`, `image` | social (image defaults to `/img/og-default.png`) |
| `type` | OG type (`website` default) |
| `noindex` | `true` for 404/utility pages |
| `canonical` | path override (else derived from the URL) |
| `jsonLd` | array of JSON-LD objects (one `<script>` each) |

### `SiteScripts.astro`
All client behaviour, one bundled module, guarded per page; rendered once by `BaseLayout`. No props.
Covers: mobile nav + navbar scroll-collapse (`--nav-scroll-p`) + dark-glass flip
(`.navbar--over-dark` via IO), scroll reveals (`[data-reveal]`), checkout accordion + idle hero
self-demo, wallet vignettes (Apple/Google Pay sheets), living-dashboard odometer (per-digit wheels,
visibility-paused), pointer tilt + shared scroll-momentum spring (`[data-tilt]`,
`[data-tilt-scroll]`), step spotlight, story fill (`--story-p`), MarketShift counter scrub, ROI
calculator glide, security-evidence switcher, legal TOC scrollspy, booking slot picker, modal.
The recipes behind these are documented in DESIGN-SYSTEM §9 — reuse them rather than inventing
new mechanisms.

---

## Layouts (`src/layouts/`)

### `BaseLayout.astro`
The page shell: loads CSS, renders `BaseHead`, skip-link, `Nav`, the `<slot/>`, `Footer`,
`EnquireModal`, `SiteScripts`. **Every page uses this** (directly or via a markdown layout). Accepts
the same SEO props as `BaseHead` plus `mainClass`.

### `ContentLayout.astro`
Markdown layout for prose pages (e.g. About). Page header (eyebrow + title + lead) + `.prose` body +
closing consultation CTA. Set `layout: ../layouts/ContentLayout.astro` + frontmatter
(`title, seoTitle, description, keywords, eyebrow, lead, path, pageType`).

### `LegalLayout.astro`
Markdown layout for legal pages. Page header + "Last updated" chip + auto **on-this-page TOC** (from
H2s) + `.prose` body. Frontmatter: `title, seoTitle, description, keywords, lastUpdated, path`.

---

## Sections (`src/components/sections/`) — the landing page

Compose these in `src/pages/index.astro`. Each is self-contained (copy lives inside the component).

| Component | What it is | Section `id` |
|---|---|---|
| `Hero.astro` | Headline + sub + CTAs + interactive checkout mockup on a navy `.stage-dark` with floating `StatusChip`s | `#hero` |
| `TrustBar.astro` | Slim one-line proof strip (trust points + live-client pill) | — |
| `CardMoment.astro` | The PBR `PayCard` as a product-shot moment high on the page — light ground, soft blue spotlight. Copy keeps it the CUSTOMER's card (we build the page they pay on, we don't issue cards). | — |
| `ValueProps.astro` | 2×2 bento of value-prop cards, each with a top-cropped mockup preview | `#about` |
| `OurWork.astro` | Split-scroll: sticky rail (header + `UKMap` canvas + link) beside stacked tilting portfolio cards | `#work` |
| `PreviewTeaser.astro` | "See Your Own Page Before You Decide" — URL form feeding the `/preview/` tool | — |
| `HowItWorks.astro` | Dark chapter: sticky dashboard + step spotlight + `FlowScene` canvas + "manual vs automated" modes | `#integration` |
| `MarketShift.astro` | Scroll-scrubbed counter pinning while the number ticks to the true UK Finance figure, then sourced stats reveal. Figures are real and attributed — verify against the named sources before changing any number. | — |
| `FastStart.astro` | Reassurance chips + 3-stage timeline + urgent-service note (slate band) | `#timeline` |
| `Compare.astro` | "Three Ways to Collect a Payment" — honest side-by-side of the alternatives | `#compare` |
| `SecurityEvidence.astro` | "Named Protections" — security evidence switcher (specific, verifiable claims only) | `#security` |
| `Calculator.astro` | Live ROI calculator (sliders → hours saved) | `#pricing` |
| `CtaBand.astro` | Closing CTA band: copy + trust list (the `PayCard` moved to `CardMoment`) | `#enquire` |
| `Sources.astro` | On-page numbered attributions for every cited figure | `#sources` |

The landing-page order in `index.astro` is: Hero, TrustBar, CardMoment, ValueProps, OurWork,
PreviewTeaser, HowItWorks, MarketShift, FastStart, Compare, SecurityEvidence, Calculator, CtaBand,
Sources.

To add a new section: create `src/components/sections/MySection.astro`, use `SectionHeader` +
`.section-pad` + `.container`, reuse tokens, and add it to `index.astro`.

`UseCases.astro` (`#testimonials`) was replaced on the landing page by `OurWork.astro`; the
component and its `.testimonials` styles remain in the repo but are no longer rendered.

---

## Mockups (`src/components/previews/`) — illustrative product UI

Pure CSS/SVG. Decorative; the only interactive one is the hero checkout (in `Hero.astro`).

| Component | What it shows |
|---|---|
| `Chrome.astro` | Browser-window chrome (dots + URL bar). Used by the previews. |
| `DashPreview.astro` | Unbranded merchant payments dashboard (KPIs + chart). |
| `Dashboard.astro` | "Engine Room" dashboard (chart + Succeeded/Synced rows) — How It Works. |
| `CheckoutTemplate.astro` | Low-fi "branded checkout template" with `[placeholder]` slots. |
| `ReconcileTemplate.astro` | Low-fi payments↔invoices auto-matcher. |
| `OnboardTemplate.astro` | Low-fi onboarding timeline (done / active / upcoming). |

**Mockups intentionally use their own 4–8px radius language** (Shopify-style) — keep them visually
distinct from the real SettlePay UI (pills + 24px cards). They are illustrative: never present them as
a real product screenshot or attach real client data.

---

## Canvas islands & hero objects (`src/components/`)

Raw WebGL, zero dependencies. Shared contract: `data-gl-state` = `live | static | unsupported`
(reduced motion draws one static frame; no WebGL leaves the DOM telling the story), IO-gated RAF,
DPR capped at 2.

| Component | What it is |
|---|---|
| `ParticleField.astro` | Ambient drifting particles behind the hero stage. |
| `FlowScene.astro` | Dark-chapter money-flow diagram: bezier tracks + travelling pulses between DOM node chips. Caption states SettlePay never holds funds. |
| `UKMap.astro` | Dot-matrix UK silhouette (mask rasterised from Natural Earth data — a hand-editable string grid). Payment arcs draw origin→destination then erase the same way, on three staggered lanes so 2–3 are usually in flight; random dots blink blue as local payments; pointer proximity lifts and warms dots. |
| `PayCard.astro` | The customer's card in `CardMoment`, rendered two ways. **Live**: the fourth WebGL island — one PBR quad (GGX + area key light + env strip) built from textures baked at runtime (albedo art, height→normal map for real embossing, roughness/metal zones, AO); the CSS `[data-tilt]` still rotates the element while the shader counter-rotates the world-fixed light, so highlights slide across the tilting face physically. Design + tuned numbers live in `inspiration/card-lighting-v2/BLUEPRINT.md`. **Fallback** (no WebGL / bake failure / context loss): the layered CSS/SVG card driven by the lerped `--px/--py/--pfc` vars — must always look finished on its own. The monogram is a hologram patch, not an issuer mark — the card must keep reading as the *customer's*; the Visa wordmark is monochrome silver (DESIGN-SYSTEM §12 exception). |

---

## Portfolio (`src/components/portfolio/`) — the /work/ case studies

Driven entirely by `src/data/portfolio.mjs`. Mock entries carry a `caseStudy` object (profile,
background, painPoints, setup, delivered, flow, ops, outcome) which `src/pages/work/[slug].astro`
renders as a full case study; the real client (Lockdales) has no `caseStudy` and keeps the plain
challenge/solution/impact layout — never attach modelled figures to a real client.

| Component | What it is |
|---|---|
| `DemoBanner.astro` | Amber disclosure strip above every interactive demo. Wording is legally load-bearing — do not edit casually. |
| `CaseFlow.astro` | Numbered automation-workflow strip. `steps=[{ title, detail }]`. |
| `OpsPanel.astro` | Back-office payment-management mockup (statuses, reminders, sync chip). `ops` from `caseStudy.ops`, `accent` = brand hex. Deliberately the same calm design on every page — the management layer is the consistent product. |
| `StatTiles.astro` | Modelled-outcome stat tiles. `outcome={ stats, basis }`. Always renders the "modelled, not measured" disclaimer — never remove it. |
| `MarshValeFlow.astro` | "Follow One Invoice" — the bespoke flagship workflow theatre (three synced panes: Xero, customer phone, ops; play/step controls, 7 steps). Rendered in place of `CaseFlow`/`CaseTheatre` when `caseStudy.flowDemo` names it. User-initiated only — never autoplays. A matching rendered video lives in `video/marsh-vale-flow/` (HyperFrames source committed; renders git-ignored). |
| `CaseTheatre.astro` | Generic, data-driven workflow theatre for the other case studies — same play/step mechanics, driven by `caseStudy.theatre` ({ intro, panes, steps }). Rebuilds rows via `innerHTML`, so its CSS lives **global** in portfolio.css (not scoped) — keep new `ct-`/`ct__` styles there. Reuses the `.ops-status--*` badge classes. |
| `RoiCalculator.astro` | "Try it on your own numbers" — interactive ROI sliders (volume × minutes × rate → hours/month + £/year), driven by `caseStudy.roi`. Always renders the "modelled, not measured" note. |
| `BrandStudio.astro` | "See it in your name" customiser on `/work/` — name + colour + scenario re-skin a live checkout; state mirrors to the URL (`?name=&colour=&plan=`) for shareable pre-branded demos. Computes a readable button text colour from the chosen accent. |
| `demos/*.astro` | The interactive brand checkouts (fixed file names — see portfolio.mjs contract): five fictional mocks, the real-client `LockdalesCheckout` (faithful navy/gold reconstruction of the live page, masked bank numbers, **no** "fictional business" banner — gated on `entry.live` in `[slug].astro`), and `CamberFinchCheckout` (fictional auction house, claret/parchment). |

Outcome figures must be modelled on citable UK sources (named in `outcome.basis`) or explicitly
labelled as assumptions. The `setup` block exists to manage expectations: never write copy promising
integration with closed systems (desktop practice software, no-API CRM tiers).

---

## Adding a new page (recipe)

1. **Prose page** → `src/pages/<name>.md` with `layout: ../layouts/ContentLayout.astro` (or
   `LegalLayout`) + SEO frontmatter.
2. **Custom page** → `src/pages/<name>.astro` using `BaseLayout` + sections/components.
3. Add it to `SITE.nav` / `SITE.footerLinks` in `site.mjs` if it should be linked.
4. Add a `seo.json` entry; pass it + JSON-LD (`webPage`, `breadcrumbs`) through the layout.
5. It's picked up by the sitemap automatically.
