# SideJob Production Server — Complete Reference

> 📍 Local path: `C:\Users\maoro\Desktop\sideJobhebrew`  
> 🔗 GitHub: https://github.com/soul-odiz/sidejob

---

## Live URLs

| Service | URL |
|---|---|
| **SideJob App** | https://sidejob.bluedune-2855dd8a.germanywestcentral.azurecontainerapps.io |
| **Health Check** | https://sidejob.bluedune-2855dd8a.germanywestcentral.azurecontainerapps.io/health |
| **Readiness Check** | https://sidejob.bluedune-2855dd8a.germanywestcentral.azurecontainerapps.io/ready |

---

## All Azure Resources

| # | Resource Type | Name | SKU/Tier | Region | Purpose |
|---|---|---|---|---|---|
| 1 | Resource Group | `portfolio-rg` | — | Global | Container for everything (shared) |
| 2 | PostgreSQL Flexible Server | `productionconnext` | B1ms (Burstable, 1 vCore, 2 GiB) | israelcentral | Shared DB server |
| 3 | PostgreSQL Database | **`sidejobdb`** | — | israelcentral | SideJob database (separate from `connextdb`) |
| 4 | Container Registry | `connextregistry` | Basic | israelcentral | Docker images (shared) |
| 5 | Container Apps Environment | `connext-env` | Consumption | germanywestcentral | Hosting environment (shared) |
| 6 | Container App | **`sidejob`** | 0.25 vCPU, 0.5 GiB, min=0, max=3 | germanywestcentral | Flask + Gunicorn + Eventlet |
| 7 | Log Analytics Workspace | `workspace-portfoliorg*` | — | germanywestcentral | Container logs (shared) |

---

## Secrets & Environment Variables

### PostgreSQL

| Key | Value |
|---|---|
| Server FQDN | `productionconnext.postgres.database.azure.com` |
| Admin Username | `connextAdmin` |
| Admin Password | `w$s15qeww` |
| Database Name | **`sidejobdb`** |
| Connection String | `postgresql://connextAdmin:w$s15qeww@productionconnext.postgres.database.azure.com:5432/sidejobdb` |

> ⚠️ `sidejobdb` is completely separate from `connextdb`. No data overlap.

### Container App Environment Variables

| Env Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://connextAdmin:w$s15qeww@productionconnext.postgres.database.azure.com:5432/sidejobdb` | Falls back to SQLite if unset |
| `SECRET_KEY` | `b6d18aee23371337f3179fbe8df4183d3c6d0dc7cd64fe07f3fa7dd142023273` | Flask session signing |
| `FLASK_ENV` | `production` | Enables HTTPS, secure cookies, disables debug |
| `DB_POOL_SIZE` | `5` | SQLAlchemy connection pool |
| `DB_POOL_RECYCLE` | `300` | Seconds before recycling connections |
| `DB_MAX_OVERFLOW` | `10` | Extra connections beyond pool_size |

### Optional (not currently set)

| Env Variable | Purpose |
|---|---|
| `REDIS_URL` | Redis for distributed rate limiting (uses in-memory fallback) |
| `LOG_LEVEL` | Logging verbosity (defaults to WARNING) |

### Container Registry

| Key | Value |
|---|---|
| Login Server | `connextregistry.azurecr.io` |
| Admin Username | `connextregistry` |
| Image | `connextregistry.azurecr.io/sidejob:latest` |

---

## Docker Image

| Property | Value |
|---|---|
| Base Image | `python:3.11-slim` |
| WSGI Server | Gunicorn 21.2.0 |
| Worker Class | Eventlet 0.36.1 (WebSocket support) |
## Security Features (active in v6)

| Feature | Implementation |
|---|---|
| **HTTPS enforcement** | Flask-Talisman `force_https=True` |
| **CSP** | `default-src 'self'; script-src ... CDNs; connect-src ws: wss:` |
| **HSTS** | `max-age=31556926; includeSubDomains` |
| **X-Frame-Options** | `SAMEORIGIN` |
| **X-Content-Type-Options** | `nosniff` |
| **CSRF protection** | Auto-injected on all POST forms via base.html JS |
| **Rate limiting** | 10/min login, 5/min signup, 200/day global |
| **Session cookies** | Secure + HttpOnly + SameSite=Lax |
| **SocketIO auth** | Rejects unauthenticated WebSocket connections |
| **Secret key** | Random `secrets.token_hex(32)` fallback if env var unset |
| **Debug mode** | Disabled when `FLASK_ENV=production` |

---

## Deploy Commands

### Full Rebuild & Deploy
```powershell
# 1. Login
az acr login --name connextregistry

# 2. Build
docker build -t connextregistry.azurecr.io/sidejob:latest `
  -f C:\Users\maoro\Desktop\sideJobhebrew\Dockerfile `
  C:\Users\maoro\Desktop\sideJobhebrew\

# 3. Push
docker push connextregistry.azurecr.io/sidejob:latest

# 4. Deploy (PowerShell — note $ escaping!)
$dbUrl = 'postgresql://connextAdmin:w$s15qeww@productionconnext.postgres.database.azure.com:5432/sidejobdb'
python -m azure.cli containerapp update `
  --resource-group portfolio-rg --name sidejob `
  --image connextregistry.azurecr.io/sidejob:latest `
  --revision-suffix v{NEXT} `
  --set-env-vars DATABASE_URL=$dbUrl SECRET_KEY=b6d18aee... FLASK_ENV=production
```

### Update env vars only (no rebuild)
```powershell
python -m azure.cli containerapp update --resource-group portfolio-rg --name sidejob --set-env-vars KEY=value
```

### View logs
```powershell
az containerapp logs show --resource-group portfolio-rg --name sidejob --tail 50
```

### Health check
```powershell
Invoke-RestMethod https://sidejob.bluedune-2855dd8a.germanywestcentral.azurecontainerapps.io/health
```

---

## Architecture Flow

```
Browser (Customer / Crew Member)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  sidejob  (Gunicorn + Eventlet:5000)                      │
│  Flask SSR — server-rendered Hebrew templates             │
│  Auth, bookings, errands, chat (SocketIO), reviews       │
│  min=0, max=3, 0.25 vCPU, 0.5 GiB                        │
│  germanywestcentral                                        │
└──────────────────┬───────────────────────────────────────┘
                   │
            ┌──────▼──────┐
            │ PostgreSQL   │
            │ sidejobdb    │  ← separate database
            │ B1ms 1vCore  │
            │ israelcentral│
            │ 32 GB        │
            └──────────────┘
```

- **No CDN/SPA** — server-rendered templates with external CDN scripts
- **No blob storage** — file uploads are local/ephemeral (`static/uploads/`)
- **No Redis** — rate limiting uses in-memory storage
- **SocketIO** via WebSocket (`--transport auto`)

---

## Database Tables

Auto-created at startup via `db.create_all()`:
```
user, profile, profession, crew_member, crew_member_profession,
working_hour, booking, review, transaction, notification,
chat_message, cart_item, crew_member_hire, errand, proposal
```

---

## Shared vs Dedicated Resources

| Resource | Shared with Connext? | Isolation |
|---|---|---|
| Resource Group (`portfolio-rg`) | ✅ Shared | N/A |
| PostgreSQL Server (`productionconnext`) | ✅ Shared | **Separate database** (`sidejobdb`) |
| Container Registry (`connextregistry`) | ✅ Shared | Separate image (`sidejob:latest`) |
| Container Apps Env (`connext-env`) | ✅ Shared | Separate Container App (`sidejob`) |
| Storage Account (`portfoliostg01`) | ❌ Not used | N/A (uploads are local/ephemeral) |
| Redis | ❌ None | N/A (memory fallback) |

---

## Known Limitations

1. **File uploads ephemeral**: Wiped on container restart. Add Azure Blob Storage for persistence.
2. **Cold start**: `min-replicas=0` — ~5-10s delay on first visit. Set `min-replicas=1` (~$14/mo).
3. **No email verification**: Passwords hashed but no confirmation or 2FA.
4. **Redis not provisioned**: Rate limiting per-instance. Add Redis for global limits across replicas.
5. **PostgreSQL firewall**: Only Azure services can connect from outside.

---

## Revision History

| Rev | Date | Changes |
|---|---|---|
| v1 | Aug 8, 2026 | Initial deploy — SQLite, basic Flask |
| v2 | Aug 8, 2026 | Added PostgreSQL (`sidejobdb`) |
| v3 | Aug 8, 2026 | Talisman, Limiter, CSRF, health endpoints (crashed — bad DB password) |
| v4 | Aug 8, 2026 | Fixed session_cookie_same_site (crashed — bad DB password) |
| v5 | Aug 8, 2026 | Fixed DB password escaping (crashed — backtick in env var) |
| **v6** | **Aug 8, 2026** | **✅ Working — all security features active** |

| Workers | 1 (required for SocketIO sticky sessions) |
| Port | 5000 |
| Health Check | `python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')"` |

### Key Dependencies

```
flask==2.3.2, flask_sqlalchemy==3.0.3, flask_socketio==5.3.4
flask_talisman==1.0.0, flask_limiter==3.5.0
psycopg2-binary==2.9.9, redis==5.0.1
gunicorn==21.2.0, eventlet==0.36.1
```