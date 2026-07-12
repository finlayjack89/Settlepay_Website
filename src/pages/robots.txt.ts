import type { APIRoute } from 'astro';
import { SITE } from '../data/site.mjs';

export const GET: APIRoute = () =>
  new Response(
    `# https://settlepay.uk robots\nUser-agent: *\nAllow: /\nDisallow: /p/\n\nSitemap: ${SITE.url}/sitemap-index.xml\n`,
    { headers: { 'Content-Type': 'text/plain; charset=utf-8' } }
  );
