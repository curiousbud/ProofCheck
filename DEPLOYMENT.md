# Deploying ProofCheck

This guide covers how to deploy ProofCheck to Docker, container/PaaS platforms
(Cloud Run, Render, Railway, Fly.io, Heroku, AWS, Azure, DigitalOcean), a plain VPS, and
how to use Netlify / Vercel for the frontend.

Ready-made config files live in [`deploy/`](deploy/), plus a [`Dockerfile`](Dockerfile),
[`docker-compose.yml`](docker-compose.yml), and [`.dockerignore`](.dockerignore) at the repo root.

---

## 0. Read this first — what ProofCheck needs

ProofCheck is **not a static website**. It's a Python **FastAPI** app (served by uvicorn)
with a server-side processing pipeline. The bundled single-page UI is served *by* the
backend and only works against its `/api/*` endpoints. So a deployment target must be able to:

| Requirement | Why |
|-------------|-----|
| Run a long-lived Python process | It's an ASGI web server, not serverless-friendly (uploads + OCR can take seconds). |
| Provide the **Tesseract binary** | Needed for the optional OCR of scanned PDFs. Pure pip can't supply it. |
| A writable filesystem | Temp upload files (deleted immediately), a short-lived report cache, and — if you enable auth/history — a SQLite DB + OCR cache you'll want to **persist on a volume**. |

**Consequence:**
- **Container / PaaS / VPS hosts run the whole app** (recommended) — Docker, Cloud Run,
  Render, Railway, Fly.io, Heroku, AWS, Azure, DigitalOcean, or your own server.
- **Netlify & Vercel** are static/serverless hosts: they can serve the **SPA** and proxy
  `/api` to a backend you host elsewhere, but they **cannot run the Python backend with
  Tesseract**. See [§11](#11-netlify-spa--proxy) / [§12](#12-vercel-spa--proxy).

### Pick a platform

| Platform | Runs full app? | OCR | Persistent history | Best for |
|----------|:---:|:---:|:---:|----------|
| Docker / Compose (§1–2) | ✅ | ✅ | ✅ (volume) | Self-hosting, any cloud VM |
| Google Cloud Run (§4) | ✅ | ✅ | ⚠️ via volume/managed DB | Scale-to-zero, pay-per-use |
| Render (§5) | ✅ | ✅ | ✅ (disk) | Easiest managed Docker |
| Railway (§6) | ✅ | ✅ | ✅ (volume) | Quick git deploys |
| Fly.io (§7) | ✅ | ✅ | ✅ (volume) | Edge regions, cheap |
| Heroku (§8) | ✅ | ✅ | ❌ ephemeral FS | Demos, stateless use |
| AWS / Azure / DO (§9–10) | ✅ | ✅ | ✅ (EFS/managed) | Enterprise / existing cloud |
| VPS + systemd (§3) | ✅ | ✅ | ✅ (local disk) | Full control, lowest cost |
| Netlify / Vercel (§11–12) | ❌ SPA only | n/a | n/a | CDN frontend + remote API |

### Environment variables (used by every method)

Full table is in the [README](README.md#configuration-env-vars). The ones that matter for deploys:

| Var | Recommended in production |
|-----|---------------------------|
| `PROOFCHECK_SECRET` | A long random hex (`python -c "import secrets;print(secrets.token_hex(32))"`). Stable across restarts so sessions survive. |
| `PROOFCHECK_AUTH` | `on` if the instance is public; set `PROOFCHECK_ADMIN_USER` / `PROOFCHECK_ADMIN_PASSWORD`. |
| `PROOFCHECK_DB` | A path on a persistent volume, e.g. `/data/proofcheck.db`. |
| `PROOFCHECK_OCR_CACHE` | A path on a persistent volume, e.g. `/data/ocr_cache` (or `off`). |
| `MAX_UPLOAD_MB` | Upload size cap (default 25). |
| `CORS_ORIGINS` | Only if a separate frontend origin calls the API. |

---

## 1. Docker (recommended, runs anywhere)

The repo ships a production [`Dockerfile`](Dockerfile) that installs the Tesseract engine
and the app with its OCR extra.

```bash
# Build
docker build -t proofcheck:latest .

# Run (data persists in a named volume; set a real secret)
docker run -d --name proofcheck -p 8000:8000 \
  -e PROOFCHECK_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
  -v proofcheck-data:/data \
  proofcheck:latest
```

Open <http://localhost:8000>. Check OCR is live: `curl localhost:8000/api/health` →
`"ocr_available": true`.

Extra OCR languages: edit the `apt-get install` line in the Dockerfile to add packs, e.g.
`tesseract-ocr-ara tesseract-ocr-fra`, then use `--ocr-lang eng+ara`.

## 2. Docker Compose (single host)

[`docker-compose.yml`](docker-compose.yml) wires the volume + env for you:

```bash
# Set PROOFCHECK_SECRET in docker-compose.yml first, then:
docker compose up --build -d
docker compose logs -f
```

Put a reverse proxy (Caddy/Traefik/nginx) in front for TLS — see [§3](#3-vps-without-docker-systemd--nginx).

## Scaling

OCR is CPU-bound. Scale by **workers per container** and/or **replicas**:
- More workers in one container: append `--workers 4` to the `CMD` (rule of thumb: ~1 per CPU core).
- More replicas: run several containers behind a load balancer (most PaaS options below do this for you).
- Give each instance enough RAM — rendering a PDF page at 300 DPI for OCR can use 100s of MB.

---

## 3. VPS without Docker (systemd + nginx)

On a fresh Ubuntu/Debian box:

```bash
sudo apt-get update && sudo apt-get install -y python3-venv tesseract-ocr nginx
git clone https://github.com/Spade-IT/Proof-Reader.git /opt/proofcheck
cd /opt/proofcheck
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[ocr]"
```

Create `/etc/systemd/system/proofcheck.service`:

```ini
[Unit]
Description=ProofCheck
After=network.target

[Service]
WorkingDirectory=/opt/proofcheck
Environment=PROOFCHECK_SECRET=PUT-A-LONG-RANDOM-HEX-HERE
Environment=PROOFCHECK_DB=/opt/proofcheck/data/proofcheck.db
Environment=PROOFCHECK_OCR_CACHE=/opt/proofcheck/data/ocr_cache
Environment=PROOFCHECK_AUTH=on
Environment=PROOFCHECK_ADMIN_USER=admin
Environment=PROOFCHECK_ADMIN_PASSWORD=change-me-now
ExecStart=/opt/proofcheck/.venv/bin/uvicorn proofcheck.web.app:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /opt/proofcheck/data && sudo chown -R www-data /opt/proofcheck/data
sudo systemctl enable --now proofcheck
```

nginx reverse proxy `/etc/nginx/sites-available/proofcheck` (then symlink + reload):

```nginx
server {
    listen 80;
    server_name proofcheck.example.com;
    client_max_body_size 30m;            # >= MAX_UPLOAD_MB
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Add TLS with `sudo certbot --nginx -d proofcheck.example.com`.

---

## 4. Google Cloud Run

Serverless containers, scale-to-zero. Note: Cloud Run's container FS is in-memory and
per-instance, so for **persistent** auth/history mount a volume or use a managed DB.

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/proofcheck
gcloud run deploy proofcheck \
  --image gcr.io/PROJECT_ID/proofcheck \
  --region us-central1 --allow-unauthenticated \
  --memory 1Gi --cpu 1 --port 8000 \
  --set-env-vars PROOFCHECK_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
```

- **Stateless mode** (default): leave `PROOFCHECK_DB`/`PROOFCHECK_OCR_CACHE` pointing at the
  default temp dir — history won't persist across cold starts. Good for anonymous, on-demand checks.
- **Persistent mode**: attach a Cloud Storage FUSE volume or a Cloud Run **volume mount**,
  set `PROOFCHECK_DB=/data/proofcheck.db` and `PROOFCHECK_OCR_CACHE=/data/ocr_cache`.

## 5. Render

Use the ready [`deploy/render.yaml`](deploy/render.yaml) blueprint (Docker runtime + a 1 GB
disk at `/data` + a generated secret + health check). In Render: **New → Blueprint**, point
at the repo. Or **New → Web Service → Docker** and add a Disk mounted at `/data` manually.

## 6. Railway

Railway autodetects the `Dockerfile`. **New Project → Deploy from GitHub repo.** Then:
- Add a **Volume** mounted at `/data`.
- Variables: `PROOFCHECK_SECRET`, `PROOFCHECK_DB=/data/proofcheck.db`,
  `PROOFCHECK_OCR_CACHE=/data/ocr_cache`, and `PROOFCHECK_AUTH=on` if public.
- Railway sets `$PORT`; either keep the image's port 8000 and set the service port to 8000,
  or override the start command to `uvicorn proofcheck.web.app:app --host 0.0.0.0 --port $PORT`.

## 7. Fly.io

Use [`deploy/fly.toml`](deploy/fly.toml) (copy it to the repo root as `fly.toml`):

```bash
fly launch --no-deploy
fly volumes create proofcheck_data --size 1
fly secrets set PROOFCHECK_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
fly deploy
```

## 8. Heroku

Container deploy via [`deploy/heroku.yml`](deploy/heroku.yml) (copy to repo root as `heroku.yml`):

```bash
heroku create your-proofcheck
heroku stack:set container -a your-proofcheck
heroku config:set PROOFCHECK_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
git push heroku Areeb:main
```

⚠️ Heroku's filesystem is **ephemeral** — the SQLite DB + OCR cache reset on each restart.
Fine for demos/anonymous use; for persistent history pick a host with a real disk (§5–7).

## 9. AWS

The same image runs on any of these — pick by what you already use:
- **App Runner** — simplest: point at the image in ECR, set env vars, done. (For persistent
  history attach EFS, or run stateless.)
- **ECS Fargate** — task definition from the ECR image; mount **EFS** at `/data` for persistence;
  front with an ALB.
- **Elastic Beanstalk** (Docker platform) — push the `Dockerfile`; add EFS for `/data`.

```bash
aws ecr create-repository --repository-name proofcheck
docker build -t proofcheck . && docker tag proofcheck:latest <acct>.dkr.ecr.<region>.amazonaws.com/proofcheck:latest
docker push <acct>.dkr.ecr.<region>.amazonaws.com/proofcheck:latest
```

## 10. Azure / DigitalOcean

- **Azure Container Apps** (or App Service for Containers): deploy the image, set env vars,
  attach an **Azure Files** mount at `/data` for persistence.
- **DigitalOcean App Platform**: **Create → App → Dockerfile**; add a small **Volume** at
  `/data`; set the env vars; health check `/api/health`.

---

## 11. Netlify (SPA + proxy)

Netlify **cannot run the Python backend or OCR**. The supported pattern is: host the **SPA**
on Netlify's CDN and **proxy** `/api` + `/reports` to a backend you deployed via §1–10.

Use [`deploy/netlify.toml`](deploy/netlify.toml) (copy to the repo root as `netlify.toml`),
replacing `BACKEND.example.com` with your backend's HTTPS host. It:
- publishes `proofcheck/web/static`,
- maps `/static/*` to the publish root (where `app.js`/`app.css` live),
- proxies `/api/*` and `/reports/*` to your backend (server-side, so the browser sees
  same-origin requests and the session cookie keeps working).

Deploy: connect the repo in Netlify (no build command needed). Because the proxy makes the
API same-origin, you usually **don't** need to set `CORS_ORIGINS` on the backend.

## 12. Vercel (SPA + proxy)

Same idea as Netlify. Use [`deploy/vercel.json`](deploy/vercel.json) (copy to the repo root
as `vercel.json`), set **Framework Preset: Other**, no build command, output directory
`proofcheck/web/static`, and replace `BACKEND.example.com`.

> Could Vercel run the API as a Python serverless function? Only in a degraded way — there's
> **no Tesseract binary** (OCR disabled), only `/tmp` is writable (no persistent history),
> and request timeouts are short. For the real app, host the backend per §1–10 and use
> Vercel just for the SPA + proxy above.

---

## Production checklist

- [ ] Set a stable **`PROOFCHECK_SECRET`** (random hex) so sessions survive restarts.
- [ ] If public, set **`PROOFCHECK_AUTH=on`** + an admin user/password.
- [ ] Mount a **persistent volume** and point `PROOFCHECK_DB` / `PROOFCHECK_OCR_CACHE` at it
      (or accept stateless mode where history doesn't persist).
- [ ] Serve over **HTTPS** (reverse proxy or the platform's TLS); session cookies are HttpOnly.
- [ ] Set **`MAX_UPLOAD_MB`** and the proxy's body-size limit to match.
- [ ] Install the **Tesseract language packs** you need; verify `/api/health` →
      `"ocr_available": true`.
- [ ] Size CPU/RAM for OCR and add **workers/replicas** under load.
- [ ] Monitor **`GET /api/health`** for liveness.
