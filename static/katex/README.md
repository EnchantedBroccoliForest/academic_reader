# Vendored KaTeX 0.16.11

Copied from the `katex@0.16.11` npm package (`dist/`), not modified except:

- only the `woff2` fonts are shipped (every browser since ~2016 supports them),
  and the matching `woff`/`truetype` `src:` entries were removed from
  `katex.min.css` so nothing 404s.

Previously this was loaded from jsDelivr. It is vendored so a self-hosted
reader renders math without reaching the network.

To update: `npm pack katex@<version>`, copy `dist/katex.min.css`,
`dist/katex.min.js`, `dist/contrib/auto-render.min.js` and `dist/fonts/*.woff2`,
then re-apply the `src:` trim.

KaTeX is MIT licensed; see LICENSE.
