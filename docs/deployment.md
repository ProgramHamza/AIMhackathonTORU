# Deployment: frontend on Vercel, backend on Render (both free)

Only the invented sample patient (`sample-data/`) goes online. Never deploy the challenge dataset.

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
   It answers `{"ok": true, "patients": 1}`.

If Render gives the service a different address (the name was taken), copy it into
`frontend/vercel.json` (`destination`) and push.

### Optional: a private default patient

The repository only contains the invented sample patient. To open the live demo on another record
(for example the challenge patient) without putting it into the repository:

1. Locally: `cd backend && python -m app.importer --bundle <patient folder> eval/private/patient-bundle.json`
   (`eval/private/` is gitignored). This packs `patient.json` and `documents/` into one file.
2. On Render: service → **Environment** → **Secret Files** → add a file named `patient-bundle.json` and
   paste the file's content. Secret files never enter the repository; Render mounts them at
   `/etc/secrets/`.
3. Redeploy. At startup the server imports the bundle (`IMPORT_BUNDLE` in `render.yaml`) and makes
   it the default patient: an empty name and date of birth in the UI open it. Without the secret file
   the sample patient stays the default.

Anyone who has the demo URL can read that record, so only use data you are allowed to show.

Free-plan behaviour: the service sleeps after 15 minutes without requests; the next request wakes
it in about a minute (it rebuilds the search index). Imported patients live in memory and on the
temporary disk, so they are gone after a restart. Set `ALLOW_IMPORT=0` to turn uploads off.

## 2. Frontend on Vercel

1. Sign in at vercel.com with GitHub. Choose **Add New → Project** and import this repository.
2. Set **Root Directory** to `frontend`. Vercel detects Vite (build `npm run build`, output `dist`).
3. Deploy. The bundled demo patient works without the backend; searching the sample patient
   (empty name and date of birth, or "Eva Probst", 1957-09-02) and importing go through `/api`
   to Render.

Uploads pass through Vercel's rewrite, which limits request bodies to a few MB: plenty for a
patient folder (the sample is about 15 KB).

## Running the same thing locally

```bash
cd backend && python -m app.server --patient ../sample-data/patient-9001-0001
cd frontend && npm ci && npm run dev
```

## Notes

- The API has no login. Anyone with the URL can query the sample patient and upload files, and
  requests use your free Gemini quota (no cost; rate limits apply).
- Every text sent to Gemini passes the de-identification gate; the hosted service still carries
  synthetic data only (`docs/data-protection.md`).
