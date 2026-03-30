# Workshop slides (GitHub Pages)

Vite + React + TypeScript + Tailwind, with a full-screen `FallingPattern` background (same idea as shadcn’s `components/ui` layout and `@/lib/utils`).

## Local preview

```bash
cd slides
npm install
npm run dev
```

Production build (base path defaults to `/` locally; on GitHub Actions `GITHUB_REPOSITORY` sets `/repo-name/`):

```bash
GITHUB_REPOSITORY=owner/repo-name npm run build
npm run preview
```

## GitHub Pages

1. Repository **Settings → Pages → Build and deployment**.
2. Set **Source** to **GitHub Actions** (not “Deploy from a branch”).
3. Push to `main` (or run **Actions → Deploy slides to GitHub Pages → Run workflow**).

The site URL is `https://<user>.github.io/<repo>/`.

## Fresh shadcn-style app (if you start elsewhere)

```bash
npx shadcn@latest init
```

Use **TypeScript**, **Tailwind**, and alias `@/*` → `src/*`. Put shared UI in `src/components/ui` so imports like `@/components/ui/falling-pattern` match ecosystem docs and generators. Install `framer-motion` for `FallingPattern`.
