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
<Button variant="primary" icon="arrow" enquire>Enquire Now</Button>
<Button variant="secondary" href="/faq/">Read the FAQ</Button>
<Button variant="primary" size="large" onDark enquire>Book a Free Consultation</Button>
```
**Use when:** any call to action. For "open the enquiry form" use `enquire`; for navigation use `href`.
Standard CTA labels: **"Enquire Now"** in compact chrome (nav/hero), **"Book a Free Consultation"** for
long-form CTAs.

### `Icon.astro`
Heroicons v2 outline, inline SVG, `currentColor`.

| Prop | Type | Default |
|---|---|---|
| `name` | string (key in the path map) | falls back to `check` |
| `sw` | number (stroke width) | `1.5` |
| `class` / `style` | — | — |

Available names: `phone, mail, clock, arrow, sparkles, cog, refresh, users, card, shield, lock, globe,
check, chevron, close, menu, store, scale, chat`. **Add new glyphs to the `P` map in `Icon.astro`**
(copy the exact Heroicons outline path) — never inline ad-hoc SVGs. `sw` 1.5 = decorative tiles,
2–2.5 = inline UI.

### `SectionHeader.astro`
Centred eyebrow + title (with one optional blue highlight word) + subtitle. Used atop most sections.

| Prop | Type | Notes |
|---|---|---|
| `eyebrow` | string | UPPERCASE label (badge) |
| `sentence` | boolean | sentence-case eyebrow variant (e.g. "See the impact") |
| `title` | string | plain leading text |
| `blue` | string | the highlighted word/phrase (rendered blue) |
| `titleAfter` | string | text after the blue word |
| `subtitle` | string | supporting line |

```astro
<SectionHeader eyebrow="How It Works" title="The Plumbing, " blue="Explained" subtitle="…" />
```

### `Breadcrumbs.astro`
`items={[{ name, path }]}` — last item is the current page. Used on all inner pages (also feeds
`BreadcrumbList` JSON-LD via the layouts).

---

## Chrome (site-wide)

### `Nav.astro`
Sticky floating-island nav. Links from `SITE.nav`, primary "Enquire Now" (opens modal), mobile drawer
(hamburger < 768px). No props. Edit links in `src/data/site.mjs`.

### `Footer.astro`
Two-column footer with the **honest sole-trader disclosure** (no "Ltd"). Links from `SITE.footerLinks`,
contact from `SITE`. No props.

### `EnquireModal.astro`
The free-consultation form (business, name, email, message + honeypot). Rendered once by `BaseLayout`;
opened by any `[data-enquire]` button. Submits to `SITE.formEndpoint` if set, else a mailto fallback.
No props.

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
All client behaviour (mobile nav, checkout accordion, ROI calculator, modal). One bundled module,
guarded per page. Rendered once by `BaseLayout`. No props.

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
| `Hero.astro` | Headline + sub + CTAs + interactive branded-checkout mockup | `#hero` |
| `TrustBar.astro` | Elevated white bar of 4 trust badges | — |
| `ValueProps.astro` | Four zig-zag value props, each with a live mockup preview | `#about` |
| `OurWork.astro` | Portfolio teaser cards (Live client / Illustrative demo) + disclaimer + link to `/work/` | `#work` |
| `HowItWorks.astro` | 3 numbered steps + dashboard mockup + "manual vs automated" modes | `#integration` |
| `FastStart.astro` | Reassurance chips + 3-stage timeline + urgent-service callout | `#timeline` |
| `Calculator.astro` | Live ROI calculator (sliders → hours saved) | `#pricing` |
| `CtaBand.astro` | Dark CTA band, primary + secondary | `#enquire` |

The landing-page order in `index.astro` is: Hero, TrustBar, ValueProps, OurWork, HowItWorks,
FastStart, Calculator, CtaBand.

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
