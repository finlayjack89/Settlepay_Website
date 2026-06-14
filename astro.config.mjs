// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

import { SITE } from './src/data/site.mjs';

// https://astro.build
export default defineConfig({
  // Canonical production origin — drives <link rel="canonical">, sitemap & robots.
  site: SITE.url,
  // Clean, consistent URLs (/about/) for canonical + sitemap hygiene.
  trailingSlash: 'always',
  build: {
    format: 'directory',
    inlineStylesheets: 'auto',
  },
  integrations: [
    sitemap({
      // Legal pages stay in the sitemap but we mark them lower priority.
      serialize(item) {
        if (/\/(privacy|cookies|terms)\/$/.test(item.url)) {
          item.priority = 0.3;
          item.changefreq = 'yearly';
        } else if (item.url === SITE.url + '/') {
          item.priority = 1.0;
          item.changefreq = 'monthly';
        } else {
          item.priority = 0.7;
          item.changefreq = 'monthly';
        }
        item.lastmod = SITE.lastBuilt;
        return item;
      },
    }),
  ],
});
