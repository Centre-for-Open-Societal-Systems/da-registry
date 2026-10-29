# DA Registry Staff UI

Extensible staff-ui app for the DA registry. The upstream staff-ui is cloned into `.app/` from `deps.json`. `overrides/` is copied on top.

The clone runs only when `.app/` is missing. `npm run dev`, `npm run build`, and `npm start` still apply `overrides/` so the current overlay is what Next serves.

Notes:

- Do not change anything inside `.app/`. It is generated and replaced.
- Keep the same folder structure in `overrides/` as staff-ui has inside `.app/`. 

For example, these overrides replace the same paths inside `.app/`:

| `overrides/` | replaces |
|---|---|
| `src/components/ui/StatsCard.tsx` | `.app/src/components/ui/StatsCard.tsx` |
| `src/app/[locale]/register/[type]/page.tsx` | `.app/src/app/[locale]/register/[type]/page.tsx` |

| Path | Role |
|------|------|
| `deps.json` | Git pin (`repo` / `ref` / `path`) |
| `overrides/` | DA files copied onto the same paths in `.app/` |
| `scripts/` | Clone if needed, apply overrides, install `.app` dependencies |
| `.app/` | Generated app (gitignored; do not edit) |
| `.npmrc` | `package-lock=false` — wrapper has no lockfile; app lock is `.app/package-lock.json` |

## Commands

```bash
cd da-registry/ui/staff-ui
npm install            # clone only if .app/ is missing, apply overrides, install deps
npm run dev            # apply overrides, skip clone, start Next
npm run build          # apply overrides, skip clone, build Next
npm start              # apply overrides, skip clone, start the production server
npm run reset          # delete .app/ and clone again
```

## OAN dashboard background

`overrides/src/app/[locale]/page.tsx` shows the active theme's **Dashboard Image** as one
centered, cover-sized background on the home page. The upstream pattern and the illustration
below the cards are removed. db-seed sets the image from the shared `oan_theme` in
openg2p-data. To change it, edit a custom theme's Dashboard Image in the configurator, save,
select that theme in Registry Details if it is not already active, and reload the home page.
Removing the image leaves the theme's primary background color. Factory themes remain
read-only.

## Docker

The image has no `.app/`, so `npm install` clones once. `npm run build` then skips the clone and applies `overrides/` before the Next build.

```bash
cd da-registry
docker build -f docker/staff-ui/Dockerfile \
  -t openg2p/openg2p-da-registry-staff-ui:local .
```
