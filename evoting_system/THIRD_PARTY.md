# Third-party assets served from this project

All front-end assets are served from `static/vendor/` so the pages need no
third-party host (no CDN, no Google Fonts requests). Full licence texts are in
`static/vendor/licenses/`. Downloaded on 2026-11-25.

| Asset | File(s) | Version | Source | Licence |
|---|---|---|---|---|
| Tailwind CSS Play CDN script, with the `@tailwindcss/forms` and `@tailwindcss/container-queries` plugins | `static/vendor/tailwindcss/tailwindcss-3.4.17-forms-0.5.10-container-queries-0.1.1.js` | tailwindcss 3.4.17, forms 0.5.10, container-queries 0.1.1 | `https://cdn.tailwindcss.com?plugins=forms,container-queries` (the URL the templates used), which redirected to `https://cdn.tailwindcss.com/3.4.17?plugins=forms@0.5.10,container-queries@0.1.1` | MIT — `licenses/tailwindcss-MIT.txt`, `licenses/tailwindcss-forms-MIT.txt`, `licenses/tailwindcss-container-queries-MIT.txt` (Copyright (c) Tailwind Labs, Inc.) |
| Inter (weights 300–800, normal style; latin + latin-ext subsets) | `static/vendor/fonts/inter-latin.woff2`, `inter-latin-ext.woff2` | Google Fonts build | `https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800` | SIL Open Font License 1.1 — `licenses/Inter-OFL.txt` (Copyright 2020 The Inter Project Authors) |
| JetBrains Mono (weights 500–600, normal style; latin + latin-ext subsets) | `static/vendor/fonts/jetbrains-mono-latin.woff2`, `jetbrains-mono-latin-ext.woff2` | Google Fonts build | `https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600` | SIL Open Font License 1.1 — `licenses/JetBrainsMono-OFL.txt` (Copyright 2020 The JetBrains Mono Project Authors) |
| Material Symbols Outlined (variable wght 100–700, FILL 0–1), subset to the icons the templates use: `check_circle`, `how_to_vote` | `static/vendor/fonts/material-symbols-outlined-subset.woff2` | Google Fonts v387 | `https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&icon_names=check_circle,how_to_vote` | Apache License 2.0 — `licenses/MaterialSymbols-Apache-2.0.txt` (Google) |

`static/vendor/fonts/fonts.css` holds the `@font-face` rules (from the Google Fonts
CSS responses, with `src` rewritten to the local files) and Google's
`.material-symbols-outlined` class rule. Only the latin and latin-ext subsets of
the text fonts are included; the templates contain no Cyrillic, Greek or
Vietnamese text. If a template starts using another Material Symbols icon, the
icon font must be re-downloaded with that name added to `icon_names`.

The Tailwind Play CDN script compiles the utility classes in the browser at page
load; Tailwind's documentation recommends a build step for production. That is
unchanged by vendoring it.
