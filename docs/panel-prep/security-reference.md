# Security Reference — Panel Prep

Consolidated security decisions, verification commands, and talking points for the Price Drop Monitor project.

---

## 1. Application layer (FastAPI)

### Rate limiting

**What:** SlowAPI decorators on every mutating endpoint.

| Endpoint | Limit |
|---|---|
| `GET /api/search` | 1/second |
| `POST /api/demo/drop` | 10/minute |
| `POST /api/products/force-check` | 10/minute |
| `POST /api/scheduler/prices` | 20/minute |
| `DELETE /api/scheduler/prices/{id}` | 30/minute |
| `PATCH /api/products/{id}/image` | 10/minute |

**Why:** Amazon scraping is expensive. Unlimited `/force-check` would let anyone DoS the scraper. Rate limiting is at the application layer so it applies even behind a reverse proxy.

**Verify:**
```bash
# Hit force-check 12 times — expect 200s then a 429
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/products/force-check \
    -H "Content-Type: application/json" -d '{"all":true}'
done
```

---

### Input validation — URL scheme

**What:** `PATCH /api/products/{id}/image` — Pydantic `field_validator` rejects any `image_url` that doesn't start with `http://` or `https://`.

```python
@field_validator('image_url')
@classmethod
def validate_url_scheme(cls, v):
    if v is not None and not re.match(r'^https?://', v, re.IGNORECASE):
        raise ValueError('image_url must be an http or https URL')
    return v
```

**Why:** Without this, a user could store `javascript:alert(1)` or `data:text/html,...` as the image URL. React's JSX does NOT sanitize `src` attributes — it only escapes text nodes. The `<img>` tag in most browsers won't execute `javascript:`, but SVG data URIs embedded via `data:image/svg+xml` can carry scripts and are historically buggy in webviews and older browsers. Defense-in-depth: reject at the API boundary.

**Verify:**
```bash
# Expect 422 — bad scheme
curl -s -X PATCH http://localhost:8000/api/products/1/image \
  -H "Content-Type: application/json" \
  -d '{"image_url":"javascript:alert(1)"}' | jq '.detail'

# Expect 422 — too long (>2048 chars)
curl -s -X PATCH http://localhost:8000/api/products/1/image \
  -H "Content-Type: application/json" \
  -d "{\"image_url\":\"https://$(python3 -c 'print("a"*2100)')\"}" | jq

# Expect 200 — valid URL
curl -s -X PATCH http://localhost:8000/api/products/1/image \
  -H "Content-Type: application/json" \
  -d '{"image_url":"https://m.media-amazon.com/images/I/example.jpg"}' | jq '.image_url'
```

---

### Input validation — Amazon URL / ASIN

**What:** `POST /api/products` rejects any URL that doesn't match a strict Amazon ASIN regex:

```python
_AMAZON_ASIN_URL_RE = re.compile(
    r"https?://(?:www\.)?amazon\.[a-z.]+/.*?/dp/[A-Z0-9]{10}", re.IGNORECASE
)
```

**Why:** The original check was `"amazon." in url` — a substring match. This allowed any URL containing the string "amazon." to reach Playwright, which would faithfully scrape whatever it was pointed at. That's SSRF (Server-Side Request Forgery): an attacker points the scraper at an internal service (`http://amazon.evil.com/dp/B00000000A`) or a local address (`http://169.254.169.254`). The regex forces a valid Amazon domain + ASIN structure.

**Verify:**
```bash
# Expect 400 — SSRF attempt disguised as Amazon URL
curl -s -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"url":"http://amazon.evil.com/dp/B09XWXM8R8","name":"test"}' | jq '.detail'

# Expect 400 — no ASIN
curl -s -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/s?k=lego","name":"test"}' | jq '.detail'

# Expect 201 — valid URL
curl -s -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B09XWXM8R8","name":"Aston Martin LEGO"}' | jq '.id'
```

---

### SQL injection

**What:** SQLAlchemy ORM with parameterized queries everywhere. No raw f-string SQL.

**Why:** SQLAlchemy binds all values as parameters — user input never interpolates into the query string. There is no SQL injection surface.

**Verify:**
```bash
# Path parameter — FastAPI validates int before SQLAlchemy sees it
curl -s "http://localhost:8000/api/products/1%3BDROP%20TABLE%20products/history"
# Expect: 422 (int parse failure, never reaches DB)
```

---

### XSS — stored product names

**What:** Product names are stored as-is and returned via JSON. React renders them as text nodes, not innerHTML.

**Why:** `{product.name}` in JSX compiles to `React.createElement(...)` with the string as a child — React calls `textContent`, not `innerHTML`. The string `<script>alert(1)</script>` renders as visible text, not executable HTML. The Content-Security-Policy header adds a second layer.

**Verify:**
```bash
curl -s -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.amazon.com/dp/B09XWXM8R8","name":"<script>alert(1)</script>"}' | jq '.name'
# Returns the string as-is — safe because React escapes on render, not on store
```

---

### Slack notification — mrkdwn injection prevention

**What:** `slack.py` strips `<`, `>`, `|` from product names before interpolation into Slack Block Kit mrkdwn.

**Why:** Slack's mrkdwn format uses `<URL|label>` for links. A product name containing `|evil <http://attacker.com>` would render as a link in the Slack message. Not critical, but good hygiene.

---

### No authentication on mutating endpoints

**What:** Deliberate gap. All endpoints are unauthenticated.

**Why (panel answer):** This is a demo for a personal homelab behind a private LAN. Adding auth (OAuth2, JWT, API keys) would require a user management system (user table, session store, token rotation) that doubles the project scope. The tradeoff: accessible demo vs production security. For production, the fix is FastAPI's `Depends(get_current_user)` with an OAuth2 flow or a simple API key middleware.

---

## 2. Network layer

### Docker internal network — no host port binding

**What:** In `docker-compose.prod.yml`, Postgres and Redis have no `ports:` entries. They are only addressable on the `internal` Docker bridge network.

**Why:** Docker writes iptables rules directly, bypassing UFW. If you added `ports: "5432:5432"` and then tried to block it with `ufw deny 5432`, UFW would not block it — Docker's iptables rule is evaluated first. The only reliable defense is to never bind the port to the host.

**Verify:**
```bash
# On the LXC host — should show ONLY 80 and 443
ss -tlnp | grep -E ':(5432|6379|8000|3000)'
# Expect: no output
```

---

### UFW rules

**What:** Default deny inbound. Allow 80/443 open. SSH restricted to LAN subnet only.

```bash
ufw default deny incoming
ufw allow from 192.168.1.0/24 to any port 22 proto tcp   # SSH — LAN only
ufw allow 80/tcp
ufw allow 443/tcp
```

**Why:** `ufw allow 22/tcp` opens SSH to the entire internet — any IP can attempt to brute-force login. Restricting to LAN subnet means SSH is only reachable from inside your home network or VPN. From the public internet, port 22 is just closed.

**Verify:**
```bash
ufw status verbose
# Confirm: 22/tcp has "from 192.168.1.0/24" source, not "Anywhere"

# From outside LAN (e.g. mobile hotspot or VPN off):
nc -zv <server-ip> 22    # Expect: connection refused or timeout
nc -zv <server-ip> 5432  # Expect: connection refused
nc -zv <server-ip> 80    # Expect: connection succeeded
```

---

### Two-LXC topology

**What:** Caddy in one LXC (exposed on LAN), app stack in a second LXC (no LAN route — only reachable from proxy LXC via `vmbr1` private bridge).

**Why:** Defense in depth. If an attacker exploits a vulnerability in the app (e.g. RCE via a scraper bug), they land in a container with no route to your LAN. They can't pivot to other homelab devices. The blast radius is the app container only.

**Setup:** See `docs/deploy/homelab.md` — Two-LXC topology section.

---

## 3. TLS and transport

### Caddy `tls internal`

**What:** Caddy acts as its own local CA. Generates a root cert and issues leaf certs automatically. No ACME/Let's Encrypt needed.

**Why:** `.bui` is not a public TLD — Let's Encrypt's DNS-01 challenge won't work for a domain that doesn't exist in public DNS. `tls internal` works entirely offline and auto-renews.

**Trust the root CA:**
```bash
# Export root cert from Caddy container
docker compose -f docker-compose.prod.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt

# Trust on macOS
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain caddy-root.crt

# Trust on Debian/Ubuntu
sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-local.crt
sudo update-ca-certificates
```

**Verify TLS:**
```bash
curl -sv https://amazonscraper.viet.bui/api/products 2>&1 | grep -E "SSL|TLS|issuer|subject"
# After trusting the root CA, expect: no certificate errors

# Check TLS cipher suites and grade
./testssl.sh amazonscraper.viet.bui
```

---

### HTTPS enforcement

**What:** Caddyfile has explicit HTTP→HTTPS redirect blocks and HSTS header.

```
http://amazonscraper.viet.bui {
    redir https://{host}{uri} permanent
}

Strict-Transport-Security "max-age=31536000; includeSubDomains"
```

**Why:** Without HSTS, a browser that visited `http://` once will try HTTP again next time (allowing downgrade attacks). HSTS tells the browser to always use HTTPS for this domain for 1 year, even if the user types `http://`.

---

## 4. HTTP security headers

Verify all headers are present on the live site:

```bash
curl -sI https://amazonscraper.viet.bui | grep -iE \
  "strict-transport|x-frame|x-content-type|content-security|referrer|permissions|server|x-powered"
```

| Header | Value | Protects against |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | HTTPS downgrade attacks |
| `X-Frame-Options` | `SAMEORIGIN` | Clickjacking (iframe embedding) |
| `X-Content-Type-Options` | `nosniff` | MIME sniffing attacks |
| `Content-Security-Policy` | `default-src 'self'; img-src 'self' https://m.media-amazon.com ...` | XSS, data exfiltration |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Leaking URL paths to third parties |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=()` | Browser feature abuse |
| `-Server` | (absent) | Server fingerprinting |
| `-X-Powered-By` | (absent) | Framework fingerprinting |

**Panel talking point:** The CSP allowlists `https://m.media-amazon.com` for images because Amazon product images are hosted there. A stricter CSP would use a hash or nonce per image URL, but that requires server-side templating. This is an acceptable tradeoff for a demo.

---

## 5. Redis security

**What:** Redis runs with `--maxmemory 128mb --maxmemory-policy allkeys-lru`. No AUTH configured. No host port binding.

**Why (no AUTH):** Redis AUTH is only meaningful if Redis is network-accessible. Ours is on an internal Docker network with no host binding — an attacker would need to already be inside a container to reach it. Adding a Redis password would require threading it through every service that connects. Acceptable for isolated internal usage; required for any internet-facing or multi-tenant setup.

**Why (maxmemory):** Without a memory limit, a cache-poisoning attack or a bug in the scheduler could cause Redis to consume all available RAM. `allkeys-lru` evicts the least-recently-used key when the limit is hit — the cache degrades gracefully instead of OOMing the container.

---

## 6. Panel talking points — tradeoffs

### "Why no authentication?"
Demo is behind a private LAN, accessible only to you. Adding JWT/OAuth2 requires a user table, session store, and token rotation — doubles scope. For production: `Depends(get_current_user)` in FastAPI with API key middleware is the minimal path.

### "How would you add auth without breaking the demo?"
API key middleware in FastAPI: one header `X-API-Key`, validated against an env var. Zero DB changes. Frontend stores the key in `localStorage` (or injected at build time). Adds ~20 lines. Documented as out of scope in `DESIGN.md`.

### "Why Caddy over nginx?"
Caddy handles TLS certificate issuance, renewal, and the local CA automatically. Nginx requires certbot, cron jobs, and manual cert management. For a homelab with a private TLD, Caddy's `tls internal` has no nginx equivalent — you'd need to manage a local CA with mkcert or step-ca separately.

### "Why LXC over VM?"
Shared kernel = 50 MB overhead vs 500 MB for a full VM. This stack is a web app — no kernel module requirements, no untrusted code execution. The only reason to prefer a VM here would be stricter security boundaries, which the two-LXC topology provides at the network level without paying the VM kernel tax.

### "What's the biggest security risk in this project?"
Unauthenticated mutating endpoints. Anyone on the LAN can add products, trigger scrapes, or schedule prices. Mitigated by: LAN-only access (UFW), no sensitive data stored, all operations are idempotent or reversible. For production: API key or OAuth2.

### "How did you catch the URL validation bug?"
Multi-agent QA wave: security-auditor (Opus) and code-reviewer (Sonnet) ran in parallel against the new image PATCH endpoint. Both independently flagged the missing URL scheme validation. Fixed with a Pydantic `field_validator` on both the model and a regex check on the frontend before submission.

---

## Quick verification script

Run this after every deployment to confirm the security surface:

```bash
#!/usr/bin/env bash
BASE=https://amazonscraper.viet.bui/api

echo "=== Port exposure ==="
ss -tlnp | grep -E ':(5432|6379|8000|3000)' && echo "FAIL: unexpected port open" || echo "PASS: no internal ports exposed"

echo ""
echo "=== Security headers ==="
HEADERS=$(curl -sI $BASE/products)
for h in "strict-transport" "x-frame-options" "x-content-type" "content-security-policy" "referrer-policy"; do
  echo "$HEADERS" | grep -qi "$h" && echo "PASS: $h" || echo "FAIL: $h missing"
done
echo "$HEADERS" | grep -qi "^server:" && echo "FAIL: server header present" || echo "PASS: server header absent"

echo ""
echo "=== Input validation ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH $BASE/products/1/image \
  -H "Content-Type: application/json" -d '{"image_url":"javascript:alert(1)"}')
[[ "$CODE" == "422" ]] && echo "PASS: XSS URL rejected (422)" || echo "FAIL: expected 422, got $CODE"

echo ""
echo "=== Rate limiting ==="
LAST=""
for i in $(seq 1 12); do LAST=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/products/force-check \
  -H "Content-Type: application/json" -d '{"all":true}'); done
[[ "$LAST" == "429" ]] && echo "PASS: rate limit triggered (429)" || echo "FAIL: expected 429, got $LAST"
```
