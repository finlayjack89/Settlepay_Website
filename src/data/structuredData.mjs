/**
 * JSON-LD builders. Honest schema only — SettlePay is a sole trader / service
 * business; no fabricated ratings, no "Organization" claims it can't support.
 */
import { SITE } from './site.mjs';

const base = SITE.url;

export function orgNode() {
  const node = {
    '@type': ['Organization', 'ProfessionalService'],
    '@id': base + '/#organization',
    name: SITE.name,
    url: base + '/',
    email: SITE.email,
    description: SITE.defaultDescription,
    logo: {
      '@type': 'ImageObject',
      url: base + '/assets/logos/wordmark-squircle.png',
    },
    image: base + SITE.ogImage,
    founder: { '@type': 'Person', name: SITE.legalOwner },
    address: {
      '@type': 'PostalAddress',
      streetAddress: SITE.address.line1,
      addressLocality: SITE.address.city,
      postalCode: SITE.address.postcode,
      addressCountry: SITE.address.countryCode,
    },
    areaServed: { '@type': 'Country', name: 'United Kingdom' },
    knowsAbout: [
      'Bespoke payment pages',
      'Branded checkout development',
      'Stripe integration',
      'Adyen integration',
      'GoCardless integration',
      'Payment reconciliation',
      'Xero and QuickBooks integration',
    ],
  };
  const sameAs = Object.values(SITE.social || {}).filter(Boolean);
  if (sameAs.length) node.sameAs = sameAs;
  return node;
}

export function websiteNode() {
  return {
    '@type': 'WebSite',
    '@id': base + '/#website',
    url: base + '/',
    name: SITE.name,
    description: SITE.defaultDescription,
    publisher: { '@id': base + '/#organization' },
    inLanguage: 'en-GB',
  };
}

/** Combined site graph for the home page (Organization + WebSite). */
export function siteGraph() {
  return { '@context': 'https://schema.org', '@graph': [orgNode(), websiteNode()] };
}

/** A WebPage node tied to the site graph (inner pages). */
export function webPage({ path, title, description, type = 'WebPage' }) {
  return {
    '@context': 'https://schema.org',
    '@type': type,
    '@id': base + path + '#webpage',
    url: base + path,
    name: title,
    description,
    isPartOf: { '@id': base + '/#website' },
    publisher: { '@id': base + '/#organization' },
    inLanguage: 'en-GB',
  };
}

/** BreadcrumbList — items: [{ name, path }]. */
export function breadcrumbs(items) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((it, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: it.name,
      item: base + it.path,
    })),
  };
}

/** ItemList (e.g. the /work/ portfolio) — items: [{ name, path }]. */
export function itemList({ path, name, items }) {
  return {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    '@id': base + path + '#itemlist',
    name,
    itemListElement: items.map((it, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: it.name,
      url: base + it.path,
    })),
  };
}

/** FAQPage — items: [{ question, answer }]. */
export function faqPage(items) {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: items.map((q) => ({
      '@type': 'Question',
      name: q.question,
      acceptedAnswer: { '@type': 'Answer', text: q.answer },
    })),
  };
}
