# OnePublish: YouTube Shorts → TikTok inbox drafts

A single-operator tool. It watches your YouTube channels for new Shorts, downloads each one, uploads it to your TikTok accounts as an **inbox draft**, and keeps the caption so you can paste it. The local file is deleted once every account has its draft.

```
backend/   FastAPI REST API + background worker (Python 3.12, Postgres, yt-dlp)
web/       Next.js dashboard; talks to the API only through /api/*
```

The SRS (`YT→TikTok Auto-Repost — SRS Draft.pdf`) is the original spec. These decisions override it:

- Postgres only.
- Railway only.
- `INBOX_DRAFT` is the only post mode.
- At most 5 uploads per account in any rolling 24 h.
- yt-dlp is pinned and updated through Dependabot plus a CI smoke test.
- TikTok sandbox is the permanent environment.

## How it works

The worker runs these steps in loops. The database is the only thing they share, so a crash or redeploy at any step resumes from the database.

| Step | Every | Does |
|---|---|---|
| poll | 30 s | Reads each due source's Shorts feed (`feeds/videos.xml?playlist_id=UUSH…`) and records unseen video IDs, with one job per enabled mapping. |
| download | 10 s | Downloads with yt-dlp (H.264 MP4 ≤ 1080p, PO-token plugin, cookies). Checks the file with ffprobe; remuxes or re-encodes only when needed. |
| upload | 20 s | One job per account per pass. Checks the 5-per-24 h quota, calls `inbox/video/init`, **stores `publish_id` before the first chunk**, then sends chunked `PUT`s. |
| status | 15 s | Calls `status/fetch` until `SEND_TO_USER_INBOX`, then raises a "draft ready" alert with the caption. |
| cleanup | 60 s | Deletes a file once all of its jobs have finished. A sweeper deletes anything staged for more than 24 h. |
| tokens | 30 min | Refreshes access tokens and keeps the rotated refresh token. Warns 14 days before the login expires. |

A crash mid-upload never creates a duplicate draft. Before uploading again, the job asks TikTok for the status of its stored `publish_id`. If the file already arrived, the job goes straight to `PROCESSING`. An upload that never completed produced no draft, so initialising it again is safe.

## Local development

```bash
docker compose up -d                     # postgres:17 (+ test DB) and the PO-token provider

cd backend
cp .env.example .env
uv run python scripts/gen_secrets.py              # paste TOKEN_ENC_KEY / SESSION_SECRET into .env
uv run python scripts/gen_secrets.py --password   # paste ADMIN_PASSWORD_HASH into .env
uv sync
uv run alembic upgrade head
uv run bin/start-api                     # http://localhost:8000/api/docs
uv run python -m app.worker              # in a second terminal

cd ../web
cp .env.example .env.local
pnpm install
pnpm dev                                 # http://localhost:3000
```

TikTok only redirects to HTTPS. To connect an account locally, run an HTTPS tunnel to port 3000, for example `cloudflared tunnel --url http://localhost:3000`. Then:

- register `https://<tunnel>/api/tiktok/callback` as a redirect URI in the TikTok developer portal;
- set `TIKTOK_REDIRECT_URI` and `PUBLIC_WEB_URL` to the tunnel URL.

Tests:

```bash
cd backend
DATABASE_URL=postgresql://onepublish:onepublish@localhost:5432/onepublish_test uv run alembic upgrade head
uv run pytest              # unit + integration (needs the compose Postgres)
uv run pytest -m smoke     # real YouTube: proves the pinned yt-dlp still works
cd ../web && pnpm typecheck && pnpm lint && pnpm build
```

After changing an API schema, run `pnpm gen:api` in `web/` to regenerate the typed client. CI fails if you forget.

### Phase-1 spike

Connect a sandbox account in the UI first. Then run:

```bash
uv run python scripts/spike.py --target-id 1 --channel https://www.youtube.com/@you
```

The script downloads the newest Short, uploads it to that account's inbox, polls until the upload reaches a final state, and prints the caption to paste. It writes nothing to the job tables.

## Deploying on Railway

Create one Railway project from this GitHub repo with five services:

| Service | Source | Settings |
|---|---|---|
| **Postgres** | Railway Postgres database | none |
| **api** | repo, root `/backend`, config file `/backend/railway.api.json` | No public domain. The pre-deploy step runs `alembic upgrade head`. |
| **worker** | repo, root `/backend`, config file `/backend/railway.worker.json` | Add a **volume mounted at `/data`**. Keep it at 1 replica. |
| **web** | repo, root `/web`, config file `/web/railway.json` | Generate a **public domain**. |
| **pot-provider** | Docker image `brainicism/bgutil-ytdlp-pot-provider:2.0.2` | Private only. Its major version must match the `bgutil-ytdlp-pot-provider` pin in `backend/pyproject.toml`. |

Variables. Use Railway's shared variables, or set them on each service:

| Variable | api | worker | web |
|---|---|---|---|
| `DATABASE_URL=${{Postgres.DATABASE_URL}}` | ✓ | ✓ | |
| `TOKEN_ENC_KEY`, `SESSION_SECRET` | ✓ | ✓ | |
| `ADMIN_PASSWORD_HASH` | ✓ | | |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | ✓ | ✓ | |
| `TIKTOK_REDIRECT_URI=https://${{web.RAILWAY_PUBLIC_DOMAIN}}/api/tiktok/callback` | ✓ | | |
| `PUBLIC_WEB_URL=https://${{web.RAILWAY_PUBLIC_DOMAIN}}` | ✓ | | |
| `STAGING_DIR=/data/staging`, `YTDLP_COOKIES_PATH=/data/cookies.txt` | | ✓ | |
| `POT_PROVIDER_URL=http://${{pot-provider.RAILWAY_PRIVATE_DOMAIN}}:4416` | | ✓ | |
| `YTDLP_COOKIES_B64` (base64 cookies.txt from a throwaway Google account) | | ✓ | |
| `YTDLP_PROXY` (optional residential proxy, used by yt-dlp only) | | ✓ | |
| `API_INTERNAL_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000` | | | ✓ |
| `PORT=8000` | ✓ | | |

In the TikTok developer portal (Sandbox):

- add the Login Kit and the Content Posting API with the `video.upload` scope (plus `user.info.basic`);
- register the redirect URI above;
- add each TikTok account you'll post to as a sandbox **target user**.

### Updating yt-dlp

`yt-dlp` and the PO-token plugin are pinned in `backend/uv.lock`. The update loop:

1. Dependabot checks them every day and opens a PR.
2. CI runs the tests and a smoke test that extracts a real Short.
3. If CI passes, the `automerge-ytdlp` job merges the PR.
4. Railway redeploys api and worker from `main`.

To roll back, redeploy the previous deployment in Railway.

The auto-merge needs two repo settings:

- Settings → Actions → General → *Workflow permissions: Read and write*;
- *Allow GitHub Actions to approve pull requests*.

If GitHub's runners hit YouTube's bot check, add a `YTDLP_COOKIES_B64` repo secret.

If YouTube breaks yt-dlp before a fix ships, downloads fail and raise an alert. Jobs wait for up to 24 h, so nothing is lost until the sweeper runs. To update by hand: `uv lock --upgrade-package yt-dlp`, then commit and push.

### Refreshing YouTube cookies

When the alerts page shows "YouTube is asking the server to sign in", export fresh cookies from a logged-in private window of the throwaway account and run `base64 -i cookies.txt | pbcopy`. Paste the result into `YTDLP_COOKIES_B64` on the worker, then redeploy.
