/**
 * SettlePay — single source of truth for site-wide facts.
 * Used by pages, components, structured data (JSON-LD), sitemap and robots.
 *
 * IMPORTANT (legal): SettlePay is a TRADING NAME of Finlay Salisbury, a sole trader.
 * It is NOT a limited company — there is no company number and it is not
 * "registered in England & Wales". Do not reintroduce "Ltd" anywhere.
 */
export const SITE = {
  name: 'SettlePay',
  // Legal / sole-trader identity
  legalOwner: 'Finlay Salisbury',
  tradingStatement: 'SettlePay is a trading name of Finlay Salisbury.',
  legalForm: 'Sole trader',

  url: 'https://settlepay.uk',
  // Used for canonical defaults, OG, and sitemap lastmod.
  lastBuilt: '2026-06-07',

  // Contact
  email: 'hello@settlepay.uk',
  emailConsultations: 'consultations@settlepay.uk',
  address: {
    line1: '2b Rodney Street',
    city: 'London',
    postcode: 'N1 9FS',
    region: 'England',
    country: 'United Kingdom',
    countryCode: 'GB',
  },

  // Data protection — fill in once registered with the ICO.
  icoRegistration: '[ICO_REGISTRATION_NUMBER]',

  // Enquiry form delivery endpoint — the Supabase `enquiry` Edge Function.
  // Stores each submission in the `leads` table and emails a notification via Resend.
  // Leave empty to fall back to the no-backend mailto: flow.
  formEndpoint: 'https://xqpbcoldcqfxfwhcqlcy.supabase.co/functions/v1/enquiry',

  // "See your payment page" preview — the Supabase `brand-preview` Edge Function
  // (same project as the enquiry endpoint). Reads a visitor's public brand via
  // Brandfetch and drafts microcopy via Claude. Requires the function to be
  // deployed and BRANDFETCH_API_KEY / ANTHROPIC_API_KEY set as function secrets;
  // until then the /preview/ tool degrades to manual entry. Leave empty to force
  // manual-only mode.
  previewEndpoint: 'https://xqpbcoldcqfxfwhcqlcy.supabase.co/functions/v1/brand-preview',

  // Public booking page (Cal.com EU region) — secondary CTA to the enquiry form.
  bookingUrl: 'https://cal.eu/settlepay/30min',

  // Default SEO
  defaultTitle: 'SettlePay — Bespoke Payment Pages for UK Businesses',
  titleTemplate: '%s · SettlePay',
  defaultDescription:
    'SettlePay designs and builds bespoke, branded checkout pages for small UK businesses, connecting you to FCA-regulated processors so you stop chasing bank transfers and automate reconciliation.',
  ogImage: '/img/og-default.png',
  locale: 'en_GB',
  themeColor: '#0F172A',

  // The third-party processors we integrate (clients hold their own accounts).
  processors: ['Stripe', 'Adyen', 'Checkout.com', 'GoCardless'],

  // Primary navigation (landing-page anchors + standalone pages).
  nav: [
    { label: 'How It Works', href: '/#integration' },
    { label: 'Our Work', href: '/work/' },
    { label: 'See Your Page', href: '/preview/' },
    { label: 'About', href: '/about/' },
    { label: 'Time Saved', href: '/#savings' },
    { label: 'FAQ', href: '/faq/' },
  ],

  // Footer link groups.
  footerLinks: [
    { label: 'About', href: '/about/' },
    { label: 'Our Work', href: '/work/' },
    { label: 'See Your Page', href: '/preview/' },
    { label: 'How It Works', href: '/#integration' },
    { label: 'Time Saved', href: '/#savings' },
    { label: 'FAQ', href: '/faq/' },
    { label: 'Privacy Policy', href: '/privacy/' },
    { label: 'Cookie Policy', href: '/cookies/' },
    { label: 'Terms of Service', href: '/terms/' },
  ],

  // Trust points — reused by the top TrustBar and the reassurance beat above the
  // final CTA. Copy stays within compliance (processors are FCA-regulated, not us).
  trustPoints: [
    { icon: 'card', tone: '', title: 'Modern Processors', text: 'FCA-regulated: Stripe, Adyen & more' },
    { icon: 'shield', tone: 'green', title: 'We Never Hold Funds', text: 'They settle straight to your bank' },
    { icon: 'lock', tone: 'purple', title: 'Security, Handled', text: 'PCI DSS via your processor' },
    { icon: 'check', tone: 'amber', title: 'No Lock-In, Ever', text: 'You own your account and page' },
  ],

  social: {
    // Add real profiles here when available (used in Organization JSON-LD sameAs).
  },
};

export const fullAddress = () => {
  const a = SITE.address;
  return `${a.line1}, ${a.city}, ${a.postcode}, ${a.country}`;
};
