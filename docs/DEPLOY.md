# Deploy

Single-VPS deploy via GitHub Actions → GHCR → SSH → `docker compose`. Ingress goes through a Cloudflare Tunnel (no inbound ports open on the VPS). Triggered by pushing a tag matching `v*` or by clicking **Run workflow** on the `deploy` workflow in the Actions tab.

## Stack on the VPS

```
[ user ]
   │  HTTPS
   ▼
[ Cloudflare edge ] ── Tunnel ─┐
                               │
                               ▼
                   ┌──────────────────────────────┐
                   │  VPS /opt/wealthtax-agent     │
                   │                                │
                   │  cloudflared (sidecar)         │
                   │      │                         │
                   │      ▼                         │
                   │  app   ─────►  db (postgres)   │
                   └──────────────────────────────┘
```

No public ports. Cloudflared dials *out* to the edge and proxies the hostname (`wealthtax.example.com`) to `http://app:8501` on the docker network.

## One-time GitHub setup

In GitHub repo **Settings → Environments → New environment → `production`**, then add these **Environment secrets** (not repo secrets — environment-scoped so they're only readable by the `deploy` job):

| Secret | Value |
|---|---|
| `SSH_DEPLOY_KEY` | The **private** half of an SSH key. Generate with `ssh-keygen -t ed25519 -f deploy_key -N "" -C "github-actions-deploy"`. Add the **public** half (`deploy_key.pub`) to the VPS deploy user's `~/.ssh/authorized_keys`. |
| `SSH_HOST` | The VPS hostname or IP (e.g. `vps.example.com`). |
| `SSH_USER` | The deploy user on the VPS (e.g. `deploy`). |
| `SSH_KNOWN_HOSTS` | Output of `ssh-keyscan -t ed25519,rsa -p 22 <SSH_HOST>` from any machine. Pins the host key — prevents MITM. |

Optionally add `production` environment **protection rules** (required reviewers, branch restriction to `main`) for an extra confirmation step before each deploy.

## One-time VPS setup

Assumes Docker + Docker Compose v2 already installed and the deploy user can run `docker` without `sudo`.

```bash
# As the deploy user
sudo mkdir -p /opt/wealthtax-agent
sudo chown $USER:$USER /opt/wealthtax-agent
cd /opt/wealthtax-agent

# Create .env (this file is read by docker compose)
cat > .env <<'EOF'
# Required
GROQ_API_KEY=gsk-...
WEALTHTAX_FERNET_KEY=...   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
WEALTHTAX_MODE=saas

# Database
POSTGRES_USER=wealthtax
POSTGRES_PASSWORD=...        # strong random
POSTGRES_DB=wealthtax

# Cloudflare Tunnel (see below for how to get the token)
CLOUDFLARE_TUNNEL_TOKEN=eyJh...

# Optional
SESSION_TTL_MINUTES=1440
CORRECTION_RATE_PER_MINUTE=30
LOG_LEVEL=INFO
EOF
chmod 600 .env
```

The `docker-compose.yml` itself lands on the VPS automatically — the deploy job `scp`s `docker-compose.prod.yml` from the repo to `/opt/wealthtax-agent/docker-compose.yml` on each run.

The image is pulled from GitHub Container Registry. If the repo is private, `docker login ghcr.io` once on the VPS using a PAT with `read:packages`. For a public repo, no login is needed.

## Cloudflare Tunnel setup

In the Cloudflare dashboard:

1. **Zero Trust → Networks → Tunnels → Create a tunnel**, name it (e.g. `wealthtax`). Save.
2. Pick **Docker** as the connector. Copy the **tunnel token** (a long `eyJh...` string). Paste it into `CLOUDFLARE_TUNNEL_TOKEN` in the VPS `.env` (see above). **Do not** put this token in the GitHub Actions secrets — it lives on the VPS only.
3. **Public Hostnames → Add a public hostname**:
    - Subdomain: e.g. `app`
    - Domain: your Cloudflare-managed domain
    - Service: `HTTP` → `app:8501`
4. Save. The tunnel goes live the moment `cloudflared` starts in the compose stack.

## Trigger a deploy

Two options:

**Option A — push a release tag** (recommended for production):

```bash
git tag -a v0.5.1 -m "..."
git push origin v0.5.1
```

GitHub Actions runs the `deploy` workflow on the tag. The image is tagged `:v0.5.1` and `:latest` in GHCR; the VPS pulls `:v0.5.1` and runs migrations + restart.

**Option B — manual trigger** (good for hotfixes or first-time setup):

Actions tab → `deploy` → **Run workflow** → optionally type an `image_tag` (defaults to the short SHA). Pick the branch (`main`).

## Rollback

```bash
# From any machine
gh workflow run deploy.yml -f image_tag=v0.4.0
# or via the Actions UI
```

The `image_tag` input accepts any tag that exists in `ghcr.io/vikenparikh/wealthtax-agent`. Migration: alembic only goes forward — if the rollback target predates a schema change, you'll need a hand-written downgrade migration first.

## What the deploy job actually does

1. Runs `pytest` against the source on the tagged commit. **Fails fast if tests are red.**
2. Builds `Dockerfile` and pushes the image to `ghcr.io/vikenparikh/wealthtax-agent:<tag>` + `:latest`. Uses GitHub's free build cache.
3. `scp`s `docker-compose.prod.yml` to `/opt/wealthtax-agent/docker-compose.yml` on the VPS.
4. SSHes in and runs `alembic upgrade head` against the new image (synchronous — deploy aborts if migration fails).
5. SSHes in and runs `docker compose up -d --remove-orphans` to start the new image alongside the existing stack, then prunes the old image.
6. Polls `/_stcore/health` inside the `app` container for up to 50 s. If it never returns OK, dumps the last 80 log lines and fails the job — leaving the previous image running on the VPS.

## Costs

- **GitHub Actions:** 2,000 free minutes/month for private repos (unlimited for public). A full deploy run takes ~3-4 min — comfortably free at any reasonable cadence.
- **GHCR:** Free for public repos. Free 500 MB + 1 GB egress / month for private. Tiny image (~250 MB) so even with 10 versions retained you stay free.
- **Cloudflare Tunnel:** Free, unlimited bandwidth, no card required.
- **VPS:** Whatever you already pay.
