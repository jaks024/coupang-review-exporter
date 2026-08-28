# Coupang Review CSV

A small Vercel-ready web tool that accepts a Coupang product URL, fetches every public
review page on the server, and downloads one UTF-8 CSV. Review data is returned directly
to the browser and is not stored in a database.

## What it exports

Each CSV row includes the rating, review text, masked public reviewer name, review date,
item/variant, vendor, helpful count, survey answers, image URLs, Coupang IDs, and source
URL. The exporter intentionally excludes the masked account-email field returned in
Coupang's raw response.

## Architecture

- Vite + React frontend.
- Python Vercel Function at `api/reviews.py`.
- `curl-cffi` provides a Chrome-compatible TLS/browser signature.
- `vercel.json` places the function in Seoul (`icn1`) and gives it a 60-second limit.
- Direct Coupang requests are attempted first. If they are blocked and
  `MRSCRAPER_API_KEY` is configured, the function automatically uses that managed
  fallback for the remaining pages.

The collector validates that the input is a Coupang product URL, uses only the numeric
product ID in the upstream request, paginates in batches of 30, retries temporary errors,
deduplicates review IDs, and refuses to return a partial CSV when Coupang's reported total
does not reconcile with the collected rows.

## Deploy to Vercel

1. Push this directory to a GitHub repository.
2. Import that repository in Vercel.
3. Keep the detected framework as Vite. The included `vercel.json` deploys the Python
   function in Seoul.
4. Deploy.
5. If production logs show `COUPANG_BLOCKED`, add `MRSCRAPER_API_KEY` in Vercel project
   settings and redeploy. This fallback is optional and is only called after a direct
   request is blocked.

Vercel documents Python functions and `requirements.txt` dependencies in its
[Python runtime guide](https://vercel.com/docs/functions/runtimes/python). Its
[project configuration guide](https://vercel.com/docs/project-configuration/vercel-json)
documents the `regions` and `maxDuration` settings. Vite's
[deployment guide](https://vite.dev/guide/static-deploy) describes importing a Git
repository into Vercel.

## Local development

Install the frontend and Python dependencies:

```powershell
pnpm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the local API in one terminal:

```powershell
.\.venv\Scripts\python.exe .\scripts\dev_api.py
```

Start Vite in a second terminal:

```powershell
pnpm dev
```

Vite proxies `/api` to the local Python server on port 8000.

## Verification

```powershell
pnpm test
pnpm typecheck
pnpm build
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `MRSCRAPER_API_KEY` | No | Managed fallback when Coupang blocks the deployment. |
| `COUPANG_COOKIE` | No | Fresh private/local Cookie header for direct requests. |

Do not commit `.env` files. Use public review data responsibly and follow Coupang's terms
and applicable law.

## License

MIT

