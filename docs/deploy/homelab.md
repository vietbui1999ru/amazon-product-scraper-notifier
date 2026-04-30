# Homelab Deployment Guide

Deploy the full stack (frontend, backend, docs, Postgres, Redis) behind a Caddy reverse proxy with automatic TLS on a personal homelab server.

---

## LXC vs VM — recommendation

**Use a privileged LXC container** (Proxmox CT).

|                | LXC (privileged)            | VM                             |
| -------------- | --------------------------- | ------------------------------ |
| RAM overhead   | ~50 MB                      | ~500 MB (kernel)               |
| Docker support | Yes — enable nesting        | Yes — always works             |
| Isolation      | Shared host kernel          | Full kernel isolation          |
| Disk           | 20 GB sufficient            | 20 GB sufficient               |
| Boot time      | ~2 sec                      | ~15 sec                        |
| Use case       | Web services, Docker stacks | Untrusted code, kernel modules |

This stack is a web app. You don't need kernel isolation. LXC is correct.

### Proxmox LXC setup

1. Create a Debian 12 (bookworm) CT in Proxmox
2. In CT Options → Features: enable **nesting** and **keyctl**
3. Set the container as **privileged**
4. Recommended resources: 2 vCPU, 2 GB RAM, 20 GB disk

### Install Docker inside the LXC

```bash
apt update && apt install -y curl ca-certificates gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
```

---

## DNS setup

The domain `amazonscraper.viet.bui` is a private homelab domain (`.bui` is not a public TLD). You need local DNS to resolve it.

### Option A: Pi-hole / AdGuard Home (recommended)

Add these DNS records pointing to your LXC container IP (e.g. `192.168.1.50`):

```
amazonscraper.viet.bui     A  192.168.1.50
docs.amazonscraper.viet.bui  A  192.168.1.50
```

### Option B: Router DNS override

Some routers (OPNsense, pfSense, Unifi) let you add custom DNS host entries. Add the same two `A` records above.

### Option C: /etc/hosts on each device

```
192.168.1.50   amazonscraper.viet.bui
192.168.1.50   docs.amazonscraper.viet.bui
```

---

## TLS — trusting the Caddy root CA

`tls internal` in the Caddyfile tells Caddy to act as its own local certificate authority. The root CA cert is generated on first boot and stored in the `caddy_data` Docker volume.

**You must trust this root cert on every device** that will visit the site, or browsers will show a security warning.

### Export the cert from CT 200 (the Caddy host)

Caddy runs on CT 200 (`10.0.0.50`), not in the app Docker Compose stack. Export from there:

```bash
# Export from the Caddy container on CT 200
ssh root@10.0.0.50 'docker cp caddy:/data/caddy/pki/authorities/local/root.crt /tmp/caddy-root.crt'
scp root@10.0.0.50:/tmp/caddy-root.crt ./caddy-root.crt
```

### Trust on macOS

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain caddy-root.crt
```

### Trust on Debian/Ubuntu

```bash
sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-local.crt
sudo update-ca-certificates
```

### Trust on iOS / Android

Email yourself `caddy-root.crt` and open it on device → follow the install certificate prompts → enable full trust in settings.

### Trust in Firefox (separate cert store)

Firefox uses its own trust store. Go to **Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import** and import `caddy-root.crt`. Check "Trust this CA to identify websites."

---

## Deployment

### 1. Clone and configure

```bash
git clone <your-repo-url> /opt/price-checker
cd /opt/price-checker
cp .env.example .env
```

Edit `.env`:

```env
POSTGRES_PASSWORD=changeme_use_a_strong_password
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
LOG_LEVEL=INFO
```

### 2. Deploy

```bash
./deploy.sh
```

This will:
1. Check `.env` for required vars
2. Build all Docker images
3. Start Postgres and Redis, wait for healthy
4. Run Alembic migrations
5. Start all services
6. Print the Caddy CA trust instructions

### 3. Redeploy after code changes

```bash
git pull
./deploy.sh
```

Rebuild only changed images:

```bash
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml up -d backend
```

---

## Firewall

Open only the ports Caddy needs. Block SSH from the public internet — allow it only from your home IP or VPN.

```bash
apt install -y ufw

ufw default deny incoming
ufw default allow outgoing

# SSH — restrict to your home IP or VPN subnet, NOT open to the world
# Replace 192.168.1.0/24 with your actual LAN subnet or WireGuard subnet (e.g. 10.8.0.0/24)
ufw allow from 192.168.1.0/24 to any port 22 proto tcp

# If you only want a single machine (e.g. your Mac's static IP):
# ufw allow from 192.168.1.10 to any port 22 proto tcp

# HTTP + HTTPS (Caddy only)
ufw allow 80/tcp
ufw allow 443/tcp

ufw enable
ufw status verbose
```

### Docker bypasses UFW — important caveat

Docker writes iptables rules directly and **UFW will not block ports that Docker exposes via `ports:`**, even if you add a `ufw deny` rule. This is a well-known Docker/UFW conflict.

In `docker-compose.prod.yml`, Postgres and Redis have **no `ports:` binding** — so they are unreachable from outside Docker regardless of UFW. This is the correct defense: never bind internal services to the host, not "bind and then UFW-block."

To verify nothing is accidentally exposed:

```bash
# Should show only 80 and 443 — no 5432, 6379, 8000
ss -tlnp | grep -E ':(80|443|5432|6379|8000)'
```

If you ever add `ports: "5432:5432"` for debugging, remove it before deploying — UFW alone will not protect it.

---

## Two-LXC topology (recommended for stricter isolation)

The most secure homelab setup splits Caddy and the app into separate LXC containers connected by a private internal network. The app LXC has **no direct LAN access** — only the proxy LXC does.

```
Internet / LAN
      │
      ▼
┌─────────────────┐
│  LXC 1: Proxy   │  ← exposed on LAN (192.168.1.50)
│  Caddy :80/:443 │     UFW: allow 22 from LAN, 80, 443
└────────┬────────┘
         │ private vmbr1 (10.10.0.0/30)
         ▼
┌─────────────────┐
│  LXC 2: App     │  ← NOT reachable from LAN
│  backend :8000  │     UFW: allow 22 from 10.10.0.1 only
│  frontend :80   │         allow 8000/80 from 10.10.0.1 only
│  postgres :5432 │         deny everything else
│  redis :6379    │
└─────────────────┘
```

### Proxmox setup for two-LXC

**Step 1 — Create a private bridge** in Proxmox host (`/etc/network/interfaces`):

```
auto vmbr1
iface vmbr1 inet static
    address 10.10.0.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
```

Apply: `ifreload -a` or reboot.

**Step 2 — Attach both LXCs to vmbr1** in addition to their existing network:

In Proxmox UI → each CT → Network → Add: `vmbr1`, assign static IPs:
- Proxy LXC: `eth1` = `10.10.0.2/30`
- App LXC: `eth1` = `10.10.0.3/30`

**Step 3 — UFW on the app LXC** (lock it down to proxy-only):

```bash
# On app LXC (10.10.0.3)
ufw default deny incoming
ufw default allow outgoing

# SSH only from the proxy LXC (or Proxmox host)
ufw allow from 10.10.0.2 to any port 22 proto tcp

# App traffic only from proxy LXC
ufw allow from 10.10.0.2 to any port 8000 proto tcp  # backend
ufw allow from 10.10.0.2 to any port 80 proto tcp    # frontend / docs

ufw enable
```

**Step 4 — Update `Caddyfile`** on the proxy LXC to point at the app LXC's private IP:

```
handle /api/* {
    reverse_proxy 10.10.0.3:8000
}
handle {
    reverse_proxy 10.10.0.3:80
}
```

And update `docker-compose.prod.yml` on the app LXC to bind services to the internal interface:

```yaml
frontend:
  ports:
    - "10.10.0.3:80:80"   # only reachable from private network

backend:
  ports:
    - "10.10.0.3:8000:8000"
```

The app LXC has no route to the public internet except through the proxy. Even if someone compromises the app container, they cannot reach LAN devices directly.

Postgres (5432) and Redis (6379) are not exposed to the host in `docker-compose.prod.yml` — they're only reachable on the internal Docker network.

---

## Useful commands

```bash
# Tail logs for all services
docker compose -f docker-compose.prod.yml logs -f

# Tail just the backend
docker compose -f docker-compose.prod.yml logs -f backend

# Check service status
docker compose -f docker-compose.prod.yml ps

# Restart a single service
docker compose -f docker-compose.prod.yml restart backend

# Open a postgres shell
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U pricechecker -d pricechecker

# Rebuild docs after editing markdown
docker compose -f docker-compose.prod.yml build docs
docker compose -f docker-compose.prod.yml up -d docs
```

---

## Security checklist

| Item | Status | Notes |
|---|---|---|
| Postgres not exposed to host | ✓ | No `ports:` in prod compose — Docker/UFW bypass avoided by design |
| Redis not exposed to host | ✓ | Same |
| TLS on all endpoints | ✓ | Caddy `tls internal` |
| HSTS header | ✓ | `max-age=31536000` |
| Security headers | ✓ | CSP, X-Frame-Options, etc. in Caddyfile |
| Server fingerprint removed | ✓ | `-Server`, `-X-Powered-By` headers |
| Rate limiting on API | ✓ | SlowAPI on all mutating endpoints |
| HTTP → HTTPS redirect | ✓ | Caddyfile `redir` blocks |
| UFW default deny inbound | Manual | `ufw default deny incoming` |
| 80/443 open, all else closed | Manual | UFW config in Firewall section |
| SSH restricted to home IP/VPN | Manual | `ufw allow from <subnet> to any port 22` — do NOT use `ufw allow 22/tcp` |
| SSH key-only (no password) | Manual | `PasswordAuthentication no` in `/etc/ssh/sshd_config` |
| App LXC isolated from LAN | Optional | Two-LXC topology — see section above |
| API key auth on all endpoints | ✓ | Set `API_KEY` + `VITE_API_KEY` env vars. Leave blank to disable (local dev only). |
