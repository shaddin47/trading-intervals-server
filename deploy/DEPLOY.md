# Deployment Guide

## Architecture

```
Browser (HTTPS :443)
  │
  ▼
Apache httpd (trading-intervals.cqginc.com)
  ├── /*                    → /usr/local/trading-intervals/   (React SPA, static files)
  └── /trading-intervals-server/ → http://127.0.0.1:3000/    (FastAPI via uvicorn)
```

The frontend and backend are deployed separately:
- **Frontend** — built React SPA, copied to `/usr/local/trading-intervals`
- **Backend** — Python/FastAPI app at `/usr/local/trading-intervals-server`, bound to `127.0.0.1:3000`

---

## Prerequisites (RHEL/CentOS/Rocky)

```bash
# System packages
sudo dnf install -y python3 python3-pip httpd mod_ssl

# Node.js (for building the frontend — not needed on the server if you build in CI)
sudo dnf install -y nodejs npm

# SQL Server ODBC driver (if required by your DB config)
# Follow Microsoft's RHEL install guide for msodbcsql18
```

---

## Backend installation

```bash
# Create dedicated system user
sudo useradd --system --shell /usr/sbin/nologin \
    --home /usr/local/trading-intervals-server trading-intervals

# Clone the repo
sudo git clone <repo-url> /usr/local/trading-intervals-server
sudo chown -R trading-intervals:trading-intervals /usr/local/trading-intervals-server

# Set up Python venv as the app user
sudo -u trading-intervals bash -c "
    cd /usr/local/trading-intervals-server
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
"

# Configure secrets
sudo -u trading-intervals bash -c "
    cp /usr/local/trading-intervals-server/.env.example \
       /usr/local/trading-intervals-server/.env
"
sudo nano /usr/local/trading-intervals-server/.env   # fill in DB_HOST, DB_PASSWORD, etc.

# Create cache directory
sudo -u trading-intervals mkdir -p /usr/local/trading-intervals-server/cache/{prod,stage}
```

---

## Frontend document root setup

Create the directory Apache will serve from and set ownership once:

```bash
sudo mkdir -p /usr/local/trading-intervals
sudo chown -R apache:apache /usr/local/trading-intervals
sudo chmod -R 755 /usr/local/trading-intervals
```

---

## Frontend build & deploy

Build on your dev machine (or CI) and copy the dist folder to the server:

```bash
# On dev machine / CI:
cd frontend
npm install
npm run build          # outputs to frontend/dist/

# Copy built files to server
rsync -av --delete frontend/dist/ user@server:/usr/local/trading-intervals/

# Set ownership so Apache can serve the files
ssh user@server "sudo chown -R apache:apache /usr/local/trading-intervals && sudo chmod -R 755 /usr/local/trading-intervals"  
```

Or build directly on the server:

```bash
sudo -u trading-intervals bash -c "
    cd /usr/local/trading-intervals-server/frontend
    npm install
    npm run build
"
sudo rsync -av --delete \
    /usr/local/trading-intervals-server/frontend/dist/ \
    /usr/local/trading-intervals/
# Apache (user: apache) must own the files to serve them
sudo chown -R apache:apache /usr/local/trading-intervals
sudo chmod -R 755 /usr/local/trading-intervals
```

---

## Systemd service

```bash
sudo cp deploy/trading-intervals.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-intervals
sudo systemctl status trading-intervals

# Live logs
sudo journalctl -u trading-intervals -f
```

---

## Apache configuration

```bash
# Enable required modules (add to /etc/httpd/conf.modules.d/ if not present)
# mod_proxy, mod_proxy_http, mod_rewrite, mod_headers, mod_ssl
# are typically included in the default httpd install on RHEL

# Install site config
sudo cp deploy/trading-intervals-apache.conf \
    /etc/httpd/conf.d/trading-intervals.conf

# Update SSL certificate paths in the conf file, then:
sudo apachectl configtest          # verify syntax
sudo systemctl reload httpd
```

### SSL certificate paths
Update these two lines in `trading-intervals-apache.conf` to match your cert:
```
SSLCertificateFile    /etc/pki/tls/certs/trading-intervals.crt
SSLCertificateKeyFile /etc/pki/tls/private/trading-intervals.key
```

---

## One-time DB migration (upgrading from YAML config)

After first backend start:

```bash
curl -X POST "http://localhost:3000/api/admin/migrate-yaml?env=prod"
curl -X POST "http://localhost:3000/api/admin/migrate-yaml?env=stage"
```

---

## Update procedure

```bash
# Pull latest code
cd /usr/local/trading-intervals-server
sudo -u trading-intervals git pull

# Update Python deps if requirements changed
sudo -u trading-intervals .venv/bin/pip install -r requirements.txt

# Rebuild and redeploy frontend
sudo -u trading-intervals bash -c "
    cd /usr/local/trading-intervals-server/frontend
    npm install && npm run build
"
sudo rsync -av --delete \
    /usr/local/trading-intervals-server/frontend/dist/ \
    /usr/local/trading-intervals/
sudo chown -R apache:apache /usr/local/trading-intervals
sudo chmod -R 755 /usr/local/trading-intervals

# Restart backend
sudo systemctl restart trading-intervals
```

---

## Directory layout

```
/usr/local/trading-intervals/          ← React SPA (served by Apache)
    index.html
    assets/
        *.js  *.css  *.svg ...

/usr/local/trading-intervals-server/  ← Python backend
    .env                          ← secrets (not in git)
    .venv/                        ← Python virtualenv
    backend/
    frontend/                     ← source (for building)
    cache/
        prod/
        stage/
        config.db
    config/
        market_groups.yaml
```

---

## Troubleshooting

```bash
# Check backend is listening
ss -tlnp | grep 3000

# Test backend directly
curl http://localhost:3000/api/intervals?env=prod

# Test through Apache proxy
curl https://trading-intervals.cqginc.com/trading-intervals-server/api/intervals?env=prod

# Apache logs
sudo tail -f /var/log/httpd/trading-intervals-error.log
sudo tail -f /var/log/httpd/trading-intervals-access.log

# Backend logs
sudo journalctl -u trading-intervals -f
```
