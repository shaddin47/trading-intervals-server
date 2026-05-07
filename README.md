# Trading Intervals Monitor

Compares database Order Routing Times against Windows Scheduled Tasks and Linux cron jobs, flagging scheduling gaps in a Gantt-style weekly timeline.

A **single app instance** serves both prod and stage datasets. The environment is selected per-request via `?env=prod` (default) or `?env=stage`.

---

## Architecture overview

```
trading-intervals/
├── backend/          FastAPI + Python 3.11
├── frontend/         React 18 + TypeScript + Vite
├── config/           Legacy YAML (migration source only)
├── cache/            Runtime output — git-ignored, auto-created
│   ├── prod/
│   ├── stage/
│   └── config.db     SQLite — market group overrides
├── .env              Secrets — git-ignored, copy from .env.example
├── requirements.txt
├── requirements-dev.txt
└── .vscode/
    └── launch.json
```

### What lives where

| Store | Contents | Edited by |
|---|---|---|
| `.env` | DB credentials, archive path, GitLab token, refresh interval | Sysadmin / deploy |
| SQLite `cache/config.db` | Market group display-row overrides, ignore flags, tooltip comments | Operators via Config UI |
| JSON `cache/{env}/` | Pre-computed Gantt data, refreshed every 2 hours | Background scheduler |

DB credentials **never** go into SQLite. SQLite stores **only** what operators change from the UI.

---

## Prerequisites

| Requirement | Linux | Windows |
|---|---|---|
| Python 3.11+ | `python3 --version` | `python --version` |
| Node.js 18+ | `node --version` | `node --version` |
| ODBC Driver 18 for SQL Server | [Linux install guide](https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server) | [Windows MSI](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) |
| Task archive access | CIFS/Samba mount | UNC path or mapped drive |
| GitLab access | Personal access token (`read_repository` scope) | same |

---

## Backend setup

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd trading-intervals
```

### 2. Create and activate a virtual environment

**Linux / macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (Command Prompt)**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
# If blocked by execution policy:
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

> **VS Code:** After creating the venv, open the Command Palette → _Python: Select Interpreter_ → choose `.venv`. The debugger, IntelliSense, and terminal will all use the same environment automatically.

### 3. Install Python dependencies

```bash
# Runtime only
pip install -r requirements.txt

# Runtime + dev/test tools (pytest, ruff)
pip install -r requirements-dev.txt
```

### 4. Install the ODBC driver

**Linux (Debian / Ubuntu)**
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list \
  | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18
```

**Windows** — run the MSI from Microsoft's site. The driver registers as `ODBC Driver 18 for SQL Server` — the same name used in `.env`.

### 5. Configure environment variables

```bash
cp .env.example .env
```

Minimum required values:

```dotenv
# Prod SQL Server
DB_HOST=prod-sql-server.cqginc.com
DB_NAME=CQGData
DB_USER=svc_trading_intervals
DB_PASSWORD=your-prod-password

# Stage — only fields that differ from prod
STAGE_DB_NAME=CQGDataStage

# Task archive
# Linux:
TASK_ARCHIVE_PATH=/mnt/smb/dgwnas/archive/stasks_xml
# Windows:
# TASK_ARCHIVE_PATH=\\dgwnas.cqginc.com\Archive\stasks_xml

# GitLab
GITLAB_TOKEN=glpat-xxxx
```

> Any `STAGE_DB_*` variable left blank inherits the prod value. If both envs share the same SQL Server, only `STAGE_DB_NAME` needs to be set.

### 6. Mount the task archive (Linux only)

```bash
sudo mkdir -p /mnt/smb/dgwnas
sudo mount -t cifs //dgwnas.cqginc.com/Archive /mnt/smb/dgwnas \
  -o username=YOUR_USER,password=YOUR_PASS,domain=CQGINC,vers=3.0
```

Persistent `/etc/fstab` entry:
```
//dgwnas.cqginc.com/Archive /mnt/smb/dgwnas cifs credentials=/etc/smb-creds,vers=3.0,iocharset=utf8 0 0
```

On Windows the share is accessible directly via UNC path — set `TASK_ARCHIVE_PATH` accordingly.

### 7. Start the backend

```bash
# Activate venv first
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

The app will:
- Initialise the SQLite config DB on first run
- Start a background refresh immediately if cache is empty
- Serve interactive API docs at `http://localhost:8000/docs`

### 8. (First run) Migrate legacy YAML config

If upgrading from the PowerShell version, seed SQLite once:

```bash
curl -X POST "http://localhost:8000/api/admin/migrate-yaml?yaml_path=./config/market_groups.yaml&env=prod"
curl -X POST "http://localhost:8000/api/admin/migrate-yaml?yaml_path=./config/market_groups.yaml&env=stage"
```

Safe to run multiple times — existing rows are skipped.

---

## Frontend setup

### 1. Install Node dependencies

```bash
cd frontend
npm install
```

### 2. Start the dev server

```bash
npm run dev
```

Opens at `http://localhost:3000`. The Vite dev server automatically proxies all `/api/*` requests to `http://localhost:8000` — start the backend first.

### 3. Build for production

```bash
npm run build
# Output: frontend/dist/
```

To serve the built frontend directly from FastAPI, add this to the **bottom** of `backend/main.py` (after all route registrations):

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
```

Then a single `uvicorn` process serves both API and UI on port 8000.

---

## VS Code debugging

Three configurations are included in `.vscode/launch.json`:

| Configuration | Port | Notes |
|---|---|---|
| **FastAPI: Trading Intervals (prod)** | 8000 | `APP_ENV=prod`, auto-reload enabled |
| **FastAPI: Trading Intervals (stage)** | 8001 | `APP_ENV=stage`, auto-reload enabled |
| **Pytest: All tests** | — | Runs `tests/` with debugpy attached |

Select a configuration in the **Run and Debug** panel (`Ctrl+Shift+D`) and press **F5**.

> **Tip:** If breakpoints misbehave with `--reload`, remove it from the `args` in `launch.json` and restart manually after code changes.

For the frontend, use the **Vite** extension or run `npm run dev` in the integrated terminal.

---

## Production deployment

### Linux (systemd)

Create `/etc/systemd/system/trading-intervals.service`:

```ini
[Unit]
Description=Trading Intervals Monitor
After=network.target

[Service]
Type=simple
User=your-service-user
WorkingDirectory=/opt/trading-intervals
EnvironmentFile=/opt/trading-intervals/.env
ExecStart=/opt/trading-intervals/.venv/bin/uvicorn backend.main:app \
    --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trading-intervals
sudo systemctl status trading-intervals
```

#### Frontend — build and serve

```bash
cd frontend
npm install
npm run build       # outputs to frontend/dist/
```

**Option A — FastAPI serves the static files (simplest, single process)**

Add to the **bottom** of `backend/main.py` after all route registrations:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
```

The built `frontend/dist/` directory must be present at the `WorkingDirectory` path defined in the service file. One `uvicorn` process handles both API and UI.

**Option B — nginx reverse proxy (recommended for production)**

Install nginx and create `/etc/nginx/sites-available/trading-intervals`:

```nginx
server {
    listen 80;
    server_name your-server-hostname;

    # Serve built React app
    root /opt/trading-intervals/frontend/dist;
    index index.html;

    # Client-side routing — always serve index.html for unknown paths
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API calls to FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/trading-intervals /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Windows (NSSM)

[NSSM](https://nssm.cc) wraps any executable as a Windows Service:

```powershell
# Run as Administrator
nssm install TradingIntervals "C:\trading-intervals\.venv\Scripts\uvicorn.exe"
nssm set TradingIntervals AppParameters "backend.main:app --host 0.0.0.0 --port 8000 --workers 2"
nssm set TradingIntervals AppDirectory "C:\trading-intervals"
nssm set TradingIntervals AppEnvironmentExtra `
    "DB_HOST=prod-sql-server.cqginc.com" `
    "DB_NAME=CQGData" `
    "DB_USER=svc_trading_intervals" `
    "DB_PASSWORD=your-password"
nssm start TradingIntervals
```

#### Frontend — build and serve (Windows)

```powershell
cd frontend
npm install
npm run build       # outputs to frontend\dist\
```

**Option A — FastAPI serves the static files**

Same as Linux Option A above — add the `StaticFiles` mount to `backend/main.py`. The `WorkingDirectory` set in NSSM must be the project root so that `frontend/dist` resolves correctly.

**Option B — IIS reverse proxy**

1. Install the [URL Rewrite](https://www.iis.net/downloads/microsoft/url-rewrite) and [Application Request Routing](https://www.iis.net/downloads/microsoft/application-request-routing) IIS modules.
2. Create a new IIS site pointing to `C:\trading-intervals\frontend\dist`.
3. Add a `web.config` in the dist folder:

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <!-- Proxy API calls to FastAPI -->
        <rule name="API Proxy" stopProcessing="true">
          <match url="^api/(.*)" />
          <action type="Rewrite" url="http://localhost:8000/api/{R:1}" />
        </rule>
        <!-- Client-side routing fallback -->
        <rule name="SPA Fallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
            <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

---

## Application features

### Timeline page (`/`)

- **Gantt chart** — one row per market group (trading intervals) plus one row per messenger box (uptime). Colour codes: green = OK, amber = partial coverage, red = conflict, blue = messenger uptime.
- **Env toggle** — switch between prod and stage datasets without page reload.
- **Timezone toggle** — display times in UTC, Chicago (DST-aware), or browser local time. All data is stored as UTC; conversion is client-side.
- **Filters** — filter rows by market group name or by task/box name.
- **Show ignored** — toggle visibility of market groups marked as ignored.
- **Now line** — vertical line showing the current position in the weekly cycle.
- **Hover tooltips** — start/stop times, xbits, task names, box name, source (Windows/Linux), and per-group comments.

### Sort options

The sort control in the toolbar orders market groups by:

| Option | Description |
|---|---|
| **Name** | Alphabetical by market group name |
| **Next start** | Groups whose next trading interval start is soonest |
| **Next stop** | Groups whose next trading interval stop is soonest |
| **Next execution** | Groups whose next start or stop event is soonest |

All options support ascending / descending toggle. "Next" events are calculated by mapping the current time-of-week onto the fake-week reference (`1900-04-01` = Sunday), so the sort always reflects what's actually coming up next in the weekly schedule cycle.

### Config page (`/config`)

Navigate to the **Config** tab in the top navigation bar to manage market group settings. The environment toggle (prod / stage) in the toolbar applies here too — each environment has its own independent set of overrides.

The config page shows all market groups pulled from the SQL `RouteGroup` table, merged with any existing SQLite overrides. Each row is fully inline-editable:

| Column | Description |
|---|---|
| **ID** | `RouteGroup.ID` from the database (read-only) |
| **Name** | Display label shown in the timeline row label |
| **Task name aliases** | Semicolon-separated list used to match Windows task XML and Linux cron entries (e.g. `ICE;iceuk`). If blank, the name column value is used as the only alias. |
| **Exchange keys CSV** | Comma-separated exchange key filter passed as `@ExchangeKeysCSV` to `RPT_OPS_RouteGroupTradingTimes` (e.g. `27,509`). Leave blank to return all intervals for the route group. |
| **Viable routes** | Toggle on to use `@ExchangeKeysFromViableRoutes=1` instead of a fixed CSV. Mutually exclusive with Exchange keys CSV. |
| **Ignore** | When on, the group is hidden from the timeline and its trading intervals are not fetched on each refresh. |
| **Comment** | Free text displayed in the hover tooltip for every interval bar in this group. |

**Editing:** click any cell to edit in place. Changes are saved to SQLite on focus-loss or Enter — no separate save button. A brief ✓ confirmation appears after each save.

**Adding a row:** click **+ Add row** at the top, fill in the route group ID, name, and any overrides, then click ✓ to save.

**Removing a row:** click the × button at the end of the row. The group reverts to its plain database name with no customisation (it will still appear in the timeline using the `RouteGroup.Name` value).

**Multiple rows per route group ID:** a single `RouteGroup.ID` can have multiple display rows with different exchange key filters and task name aliases (e.g. ICE UK, ICE ENDEX, ICE US all share the same route group ID but filter by different exchange key sets). Add multiple rows with the same ID and different names to achieve this.

---

## API reference

### Data

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/intervals?env=prod` | Full Gantt payload |
| `GET` | `/api/intervals/{id}?env=prod` | Single market group |

### Config (SQLite — UI editable)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/config/market-groups?env=prod` | List all override rows |
| `POST` | `/api/config/market-groups` | Create / upsert a row |
| `PUT` | `/api/config/market-groups/{id}?name=…&env=prod` | Partial update |
| `DELETE` | `/api/config/market-groups/{id}/{name}?env=prod` | Remove override row |

### Admin

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | Cache age + counts for both envs |
| `POST` | `/api/admin/refresh?env=prod` | Force immediate data refresh |
| `POST` | `/api/admin/migrate-yaml` | One-time YAML → SQLite migration |

Full Swagger UI at `http://localhost:8000/docs`.

---

## Running tests

```bash
# Activate venv first
pytest tests/ -v
```

No live DB or network connection required. Tests cover `time_utils` (fake-week normalisation, DST correction) and `comparator` (uptime interval pairing, OK / PARTIAL / CONFLICT logic).

---

## Environment variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DB_HOST` | ✅ | — | Prod SQL Server hostname |
| `DB_NAME` | ✅ | — | Prod database name |
| `DB_USER` | ✅ | — | Prod SQL login |
| `DB_PASSWORD` | ✅ | — | Prod SQL password |
| `DB_PORT` | | `1433` | Prod port |
| `DB_DRIVER` | | `ODBC Driver 18 for SQL Server` | Same name on Linux and Windows |
| `STAGE_DB_HOST` | | *(inherits prod)* | Stage hostname |
| `STAGE_DB_NAME` | | *(inherits prod)* | Stage database |
| `STAGE_DB_USER` | | *(inherits prod)* | Stage login |
| `STAGE_DB_PASSWORD` | | *(inherits prod)* | Stage password |
| `STAGE_DB_PORT` | | *(inherits prod)* | Stage port |
| `TASK_ARCHIVE_PATH` | | platform default | Linux: `/mnt/smb/…` · Windows: `\\server\share\…` |
| `GITLAB_URL` | | `https://git.at.cqg` | GitLab instance URL |
| `GITLAB_TOKEN` | | — | Personal access token (`read_repository`) |
| `GITLAB_PROJECT` | | `inventory/gateway` | Project path |
| `CACHE_DIR` | | `./cache` | Cache + SQLite location |
| `REFRESH_INTERVAL_SECS` | | `7200` | Background refresh interval (2 hours) |
| `APP_ENV` | | `prod` | Default env the scheduler refreshes |
