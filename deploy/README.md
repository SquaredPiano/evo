# Deploying Evo on a DigitalOcean Droplet

A single Droplet runs all three services (backend + Redis + frontend) with
`docker compose`. Live engines: OpenRouter (LLM), NVIDIA Evo2 40B, ESMFold,
MongoDB Atlas. Start on the raw IP; add a domain + HTTPS later with one extra
compose file.

---

## 1. Create the Droplet

- **Marketplace image:** *Docker on Ubuntu* (Docker + Compose pre-installed).
- **Size:** the Next.js build is the heaviest step - use at least **2 GB RAM / 2 vCPU**
  (Basic, ~$18/mo). 1 GB can OOM during `npm run build`. Resize down after if idle.
- Add your **SSH key**.

Note the Droplet's **public IP** (called `<DROPLET_IP>` below).

## 2. Open the firewall

In the DO console → Networking → Firewalls (or `ufw` on the box), allow inbound:

- `22` (SSH), `3000` (frontend), `8000` (backend) - for the IP-only phase.
- Later, with a domain: allow `80`, `443` and close `3000`/`8000`.

## 3. Get the code onto the Droplet

```bash
ssh root@<DROPLET_IP>
git clone <YOUR_REPO_URL> evo && cd evo
git checkout chore/digitalocean-deploy    # until this is merged to main
```

## 4. Configure secrets

```bash
cp deploy/env.production.example .env
nano .env
```

Fill in:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `http://<DROPLET_IP>:8000` |
| `FRONTEND_URL` | `http://<DROPLET_IP>:3000` |
| `OPENROUTER_API_KEY` | your OpenRouter key |
| `NVIDIA_API_KEY` | your NVIDIA NIM key |
| `MONGODB_URI` | your Atlas connection string |

`EVO2_MODE=nim_api` and `STRUCTURE_MODE=esmfold` are already set in the template.

**Atlas allowlist:** in MongoDB Atlas → Network Access → Add IP Address, add the
`<DROPLET_IP>`. Without this the store silently disables itself and the app
falls back to Redis-only (no error, just no durable history).

## 5. Launch

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

First build takes a few minutes (Next.js compile). Then:

- Frontend: `http://<DROPLET_IP>:3000`
- Backend health: `http://<DROPLET_IP>:8000/api/health`

Check status / logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
```

---

## Adding a domain + HTTPS (later)

1. Point an `A` record for your domain at `<DROPLET_IP>`.
2. In `.env` set (and note the URLs are now the domain, HTTPS):
   ```
   DOMAIN=evo.example.com
   NEXT_PUBLIC_API_URL=https://evo.example.com
   FRONTEND_URL=https://evo.example.com
   ```
3. Rebuild with the Caddy layer (frontend must be rebuilt to bake the new URL):
   ```bash
   docker compose -f docker-compose.yml \
                  -f docker-compose.prod.yml \
                  -f docker-compose.caddy.yml up -d --build
   ```
4. Caddy fetches a Let's Encrypt cert automatically. WebSockets become `wss://`
   with no code change (the backend derives the scheme from the request).
5. Close the raw ports: `ufw allow 80,443/tcp && ufw deny 8000,3000/tcp`.

---

## Updating a deployment

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## Common gotchas

- **Frontend calls `localhost:8000` in the browser** → `NEXT_PUBLIC_API_URL` was
  wrong/blank at build time. Fix `.env` and rebuild (`--build`), not just restart.
- **WebSocket won't connect** → make sure port `8000` is open (IP phase) or that
  `/ws/*` is proxied (domain phase); check `logs -f backend`.
- **No durable history** → Droplet IP not on the Atlas Network Access allowlist.
- **Build killed / OOM** → Droplet too small; use ≥2 GB RAM.
