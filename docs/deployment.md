# Deployment: frontend on Vercel, backend on Render (both free)

No patient data goes online: the service starts empty and a visitor imports a patient folder in the
browser, then types the role and task. Never commit or deploy patient records.

```
browser ── https://<project>.vercel.app ──► Vercel (frontend/, static)
                       │  /api/*  (rewrite in frontend/vercel.json)
                       ▼
           https://clinical-summary-desk-api.onrender.com ──► Render (backend/, python -m app.server)
```

## 1. Backend on Render

1. Sign in at render.com with GitHub. Choose **New → Blueprint** and pick this repository. Render reads
   `render.yaml` and creates the web service `clinical-summary-desk-api` on the free plan.
2. When asked for environment values, paste a free Gemini key into `GEMINI_API_KEY` (and optionally
   `GEMINI_API_KEY_2`). Leave them empty to run with templates only. Do not enable billing anywhere.
3. Wait for the first deploy, then open `https://clinical-summary-desk-api.onrender.com/api/health`.
   It answers `{"ok": true, "patients": 0}`.

If Render gives the service a different address (the name was taken), copy it into
`frontend/vercel.json` (`destination`) and push.

Free-plan behaviour: the service sleeps after 15 minutes without requests; the next request wakes
it in about a minute (it rebuilds the search index). Imported patients live in memory and on the
temporary disk, so they are gone after a restart. Set `ALLOW_IMPORT=0` to turn uploads off.

## 2. Frontend on Vercel

1. Sign in at vercel.com with GitHub. Choose **Add New → Project** and import this repository.
2. Set **Root Directory** to `frontend`. Vercel detects Vite (build `npm run build`, output `dist`).
3. Deploy. Importing a patient folder and every search go through `/api` to Render; nothing about a
   patient is bundled into the build.

Uploads pass through Vercel's rewrite, which limits request bodies to a few MB: plenty for a
patient folder (a folder of eight letters is a few dozen KB).

## Running the same thing locally

```bash
cd backend && python -m app.server
cd frontend && npm ci && npm run dev
```

## Notes

- The API has no login. Anyone with the URL can upload a folder and query what was imported, and
  requests use your free Gemini quota (no cost; rate limits apply). Only import synthetic records there.
- Every text sent to Gemini passes the de-identification gate (`docs/data-protection.md`).
