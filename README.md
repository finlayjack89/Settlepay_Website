# SettlePay — Marketing Website

The live marketing site for **SettlePay** — bespoke, branded payment-page development &
integration for small UK businesses. Built with [Astro](https://astro.build) as a fully static,
SEO-optimised site (zero JavaScript shipped by default; all content is in the initial HTML for
clean indexing and sitemapping).

> SettlePay is a trading name of **Finlay Salisbury** (a sole trader) — it is **not** a limited
> company. Please keep that accurate everywhere (no "Ltd", no company number, no "registered in
> England & Wales").

## Quick start

```bash
npm install        # already done
npm run dev        # local dev → http://localhost:4321
npm run build      # static build → ./dist
npm run preview    # serve the production build locally
```

## Design system & docs (read before building UI)

The brand and UI are **formalised** so anyone (or any agent) can replicate them correctly:

- **[`docs/DESIGN-SYSTEM.md`](docs/DESIGN-SYSTEM.md)** — the single source of truth: brand, voice,
  colour, typography, spacing, radii, shadows, motion, icons, logos, compliance rules.
- **[`docs/COMPONENTS.md`](docs/COMPONENTS.md)** — every component, its props, and when to use it.
- **[`CLAUDE.md`](CLAUDE.md)** — auto-loaded operating guide for AI agents (non-negotiables + where
  things live).
- **`.claude/skills/settlepay-design/`** — an invocable design skill that loads the brand rules.
- **[`src/data/site.mjs`](src/data/site.mjs)** — business facts, nav, footer, SEO defaults.

## Tech & why

- **Astro 5** — component-based, renders to static HTML at build time. Best-in-class for SEO,
  trivial to host (Netlify / Vercel / Cloudflare Pages / any static host).
- **Design system as-is** — the original pixel-perfect CSS (`src/styles/styles.css` +
  `kit-extras.css`) is the styling source of truth, driven by CSS custom properties. Tailwind can be
  layered in later without throwing any of it away.
- **Light vanilla JS** — one small bundled module (`src/components/SiteScripts.astro`) powers the
  mobile nav, hero checkout accordion, ROI calculator and the enquiry modal. Respects
  `prefers-reduced-motion`.

## Project structure

```
src/
  data/
    site.mjs              ← SINGLE SOURCE OF TRUTH: business facts, nav, footer, SEO defaults
    structuredData.mjs    ← JSON-LD builders (Organization, WebSite, FAQPage, Breadcrumb…)
    content/              ← drafted copy (about/legal markdown, faq.json, seo.json)
  components/
    BaseHead.astro        ← all <head> SEO: title, canonical, OG/Twitter, icons, fonts, JSON-LD
    Nav / Footer / Button / Icon / Breadcrumbs / EnquireModal / SiteScripts
    sections/             ← landing-page sections (Hero, ValueProps, HowItWorks, …)
    previews/             ← the CSS/SVG product mockups used in the sections
  layouts/
    BaseLayout.astro      ← page shell (loads CSS, nav, footer, modal, scripts)
    ContentLayout.astro   ← markdown layout for About
    LegalLayout.astro     ← markdown layout for legal pages (auto on-this-page TOC)
  pages/
    index.astro           ← landing page
    about.md  faq.astro  privacy.md  cookies.md  terms.md  404.astro
    robots.txt.ts         ← generated robots.txt → points at the sitemap
public/
  assets/logos, assets/payment, favicons, og image, site.webmanifest
```

## Editing common things

| Want to change…              | Edit…                                              |
|------------------------------|----------------------------------------------------|
| Business facts / email / nav | `src/data/site.mjs`                                |
| Per-page titles/descriptions | `src/data/content/seo.json`                        |
| Legal text                   | `src/pages/privacy.md`, `cookies.md`, `terms.md`   |
| About copy                   | `src/pages/about.md`                               |
| FAQ questions                | `src/data/content/faq.json` (also powers FAQ schema)|
| Landing sections             | `src/components/sections/*.astro`                  |

## SEO features (built in)

- Per-page `<title>`, meta description, keywords, canonical URL.
- Open Graph + Twitter card on every page; shareable OG image at `/img/og-default.png`.
- **Structured data (JSON-LD):** Organization + WebSite (home), WebPage + BreadcrumbList (inner
  pages), and a full **FAQPage** on `/faq/`.
- **`sitemap.xml`** auto-generated via `@astrojs/sitemap` (`/sitemap-index.xml`) with per-page
  priority/changefreq; **`robots.txt`** points to it.
- Favicons (SVG + PNG), `apple-touch-icon`, `site.webmanifest`, theme colour.
- Accessible: skip link, visible focus rings, breadcrumbs, semantic headings, reduced-motion aware,
  honeypot-protected form.

---

## ⚠️ Before going live — action items

1. **ICO registration** — register with the ICO (sole traders processing personal data normally must
   pay the annual data-protection fee), then fill `SITE.icoRegistration` in `src/data/site.mjs` with
   the issued number:
   ```bash
   grep -rl 'icoRegistration\|registration in progress' src/
   ```
   Until the number is issued, the privacy, cookies, terms and FAQ pages state that ICO **registration
   is in progress** — update that wording (and any remaining `[ICO_REGISTRATION_NUMBER]` placeholders)
   once the number comes through.
2. **Enquiry form delivery** — the form currently has no backend, so `formEndpoint` in
   `src/data/site.mjs` is unset. Until it is set, the enquiry form falls back to an honest **"open your
   mail app"** message (it no longer shows a false success). For production set `formEndpoint` to a form
   handler (Formspree / Web3Forms / Netlify Forms / a serverless function).
3. **Business address** — `2b Rodney Street, London N1 9FS` is published on the legal pages (required
   so documents can be served) and the city is shown in the footer. If you'd rather not publish a
   residential address, switch to a correspondence/virtual address in `src/data/site.mjs` and the
   legal markdown.
4. **Legal review** — the Privacy Policy, Cookie Policy and Terms were drafted to UK GDPR / PECR /
   consumer-law norms and machine-reviewed for compliance wording, **but they are not a substitute
   for advice from a solicitor.** Have them reviewed before relying on them.
5. **Hosting `settlepay.uk`** — `site` is already set to `https://settlepay.uk` in
   `astro.config.mjs`. Deploy `dist/` (or connect the repo) to your host and point the domain at it.
   After deploy, submit `https://settlepay.uk/sitemap-index.xml` in Google Search Console.
6. **Social profiles** — add any social URLs to `SITE.social` in `src/data/site.mjs` (they feed the
   Organization `sameAs` for SEO).
7. **Cookieless analytics** — add a privacy-friendly, cookieless analytics provider (e.g. Plausible /
   Fathom / Cloudflare Web Analytics) so conversions and traffic can be measured without a cookie
   banner. Once added, update the Cookie Policy wording (`src/pages/cookies.md` / its content copy) to
   describe the analytics in use.

## Notes

- `_old_site_backup/` (the previous prototype) and `_design_extract/` (the Claude Design handoff
  bundle) are kept locally but git-ignored.
