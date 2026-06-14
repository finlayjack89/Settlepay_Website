# CLAUDE.md — SettlePay website

Operating guide for any agent working in this repo. Read this, then the design docs before building UI.

## What this is
The marketing website for **SettlePay** — bespoke, branded payment-page development & integration for
small UK businesses. Built with **Astro 5** as a fully static, SEO-first site (zero JS by default).

## Read these before doing design/UI work
- **[`docs/DESIGN-SYSTEM.md`](docs/DESIGN-SYSTEM.md)** — brand, voice, colour, type, spacing, radii,
  shadows, motion, icons, logos, compliance. The source of truth for *how it looks*.
- **[`docs/COMPONENTS.md`](docs/COMPONENTS.md)** — every component, its props, and when to use it.
- **[`src/data/site.mjs`](src/data/site.mjs)** — single source of truth for business facts, nav,
  footer and SEO defaults.

## 🚫 Non-negotiable rules (legal + brand — see DESIGN-SYSTEM §2)
- SettlePay is a **trading name of Finlay Salisbury, a sole trader**. **Never** write "Ltd", a company
  number, or "registered in England & Wales".
- **Never** claim SettlePay is "FCA authorised/regulated" or "PCI DSS compliant" — payments are
  processed by **FCA-regulated partners**; PCI is handled by the client's processor.
- **No** FSCS badge, "Powered by [processor]", fake urgency, or invented metrics/case studies.
- Only **Lockdales Auctioneers** is a real client; label anything else "Illustrative example".
- UK English, Title Case headings, **no emoji**. Blue (`#3B82F6`) is reserved for the single primary
  action — never decorative. One primary + one secondary button per view.
- Reuse components (`Button`, `Icon`, `SectionHeader`, …) — don't hand-roll buttons/icons/SVGs.
  Buttons are pills (`--radius-button` 100px); inputs are `--radius-input` 8px.

## Where things live
```
src/data/site.mjs            business facts, nav, footer, SEO defaults (edit here first)
src/data/structuredData.mjs  JSON-LD builders
src/data/content/            drafted copy: about.md, faq.json, seo.json, *.md (legal)
src/styles/                  styles.css (tokens + base), kit-extras.css, site.css
src/components/              primitives, chrome, sections/, previews/
src/layouts/                 BaseLayout, ContentLayout (prose), LegalLayout (legal + TOC)
src/pages/                   index.astro, about.md, faq.astro, privacy/cookies/terms.md, 404, robots.txt.ts
public/                      assets/logos, assets/payment, favicons, og image, site.webmanifest
```

## Commands
```bash
npm run dev      # http://localhost:4321
npm run build    # static build → dist/
npm run preview  # serve the build
```

## Conventions
- **Design tokens** are CSS custom properties defined in `src/styles/styles.css` `:root`
  (`--color-*`, `--font-*`, `--radius-*`, `--shadow-*`, `--ease-*`). Use tokens, don't hardcode.
- **Adding a page:** see COMPONENTS.md → "Adding a new page". Add it to `SITE.nav`/`footerLinks` and
  `seo.json`; the sitemap picks it up automatically.
- **Icons:** add new glyphs to the path map in `Icon.astro` (exact Heroicons v2 outline path).
- **Trailing slashes** are required on internal links (`/about/`); URLs are canonical with a trailing slash.
- The hero/preview **mockups** intentionally use their own 4–8px radius (Shopify-style); keep them
  visually distinct from the real SettlePay UI.

## Go-live TODOs (tracked in README.md)
Replace `[ICO_REGISTRATION_NUMBER]` after ICO registration; set `SITE.formEndpoint` for the enquiry
form (currently mailto fallback); get the legal pages reviewed by a solicitor; deploy `dist/` to
`settlepay.uk` and submit the sitemap to Search Console.

## Verify after changes
`npm run build` must pass. For visual/behaviour changes, check `npm run dev` at localhost:4321
(interactions: mobile nav, hero checkout accordion, ROI sliders, enquiry modal).
