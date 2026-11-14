# Archive

Shelved work that is kept for reference. Nothing here is served by the backend or run by `pytest`.

## hud-app/

A React 19 + Vite + TypeScript version of the glasses HUD built on Meta's Wearables UI Toolkit
(`@wearables-ui-toolkit/mrbd`). It was archived on 2026-11-14 in favour of the plain HUD in `web/hud/`:

- Its production build is ~500 KB (401 KB JS + 100 KB CSS; ~150 KB gzipped) and it loads Noto fonts from
  Google Fonts at runtime. Meta's first-load budget for glasses web apps is under 300 KB and fewer than
  15 requests; the plain HUD was ~23 KB in 4 requests.
- It predates the ring and trend-spike redesign, so it shows the older layout.

When it was archived, its 13 Vitest tests, the TypeScript check and the production build passed under Node 24.15
(see `.nvmrc`). To run it again: `npm ci`, `npm test`, `npm run build` in this folder. Its `vite.config.ts` still
uses `base: "/hud/"` and proxies `/ws` and `/api` to the backend on port 8000. The backend does not serve it.
