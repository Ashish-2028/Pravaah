# PRAVAAH — Environment Setup & Toolchain Decisions

> Referenced by [BUILD_PLAN.md](BUILD_PLAN.md) Phase 0. Read before installing anything.

---

## 1. Current state of this machine (audited 31 Aug 2026)

| | Found |
|---|---|
| Platform | **arm64** (Apple Silicon), macOS 26.5.2 |
| Python | **`/usr/bin/python3` → 3.9.6 only.** No Homebrew python, no conda, no pyenv, no uv. |
| Homebrew | Present at `/opt/homebrew` (v6.0.14) |
| Node / npm | **v25.5.0 / 11.8.0** — installed and usable |
| Xcode CLT | Present (`/Library/Developer/CommandLineTools`) |
| Disk free | 89 GB |

**Verdict:** Node side is fine. Python side needs to be built from scratch. **System Python 3.9 is
not usable** — `numba` (which `pysheds` needs) and much of the modern geo stack no longer target it,
and you must never install project packages into the system interpreter anyway.

---

## 2. The decision: **Miniforge + conda-forge**

### Why this and not the alternatives

The hard part of this project's environment is one specific cluster:

```
pysheds → numba → llvmlite          (compiled, version-sensitive)
rasterio / fiona / pyproj → GDAL / GEOS / PROJ   (C libraries with shared ABI)
pysteps → scipy, opencv, numba
geopandas → shapely + pyproj + fiona
```

These are **not pure-Python packages**. They wrap C/C++ libraries, and the failure mode is not a
clean error — it's `ImportError: symbol not found` at hour 20, or two libraries linking against
different GDAL builds and segfaulting only on certain files.

| Option | Verdict |
|---|---|
| **Miniforge + conda-forge** ✅ **CHOSEN** | conda-forge ships GDAL/GEOS/PROJ as *real binary packages* with a guaranteed-consistent ABI across every geo package. `pysheds`, `pysteps`, `osmnx`, `rasterio` are all packaged there and known-good on arm64. It is the standard toolchain for geospatial Python for exactly this reason. Costs ~10 min and ~2 GB. |
| Homebrew python + pip | Workable but fragile. `pip` resolves GDAL bindings against whatever wheel it finds; a single missing arm64 wheel means compiling GDAL from source, which is a multi-hour detour with a real chance of failure. **Not acceptable on a one-day clock.** |
| `uv` + pip wheels | Beautifully fast, and my usual default. But it inherits the same wheel-availability risk as pip. `uv` is the right choice for a pure-Python project — this is not one. |
| `pyenv` | Solves *Python versions*. Does nothing for *C libraries*. Wrong tool for this problem. |
| Docker | Would work, adds a container layer between you and your files during the one day you most need to move fast. No. |

### The rule that prevents 90% of conda pain

> **Install the conda-forge block first, in ONE command. Then the pip block, in ONE command.
> Never go back to conda after using pip in that environment.**

Mixing them back and forth is what makes people hate conda. Done in two ordered passes, it is fine.

---

## 3. The install sequence

### Step 1 — Miniforge

**Preferred (no password, fully non-interactive):**

```bash
curl -L -o /tmp/miniforge.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh" && bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
```

**Alternative via Homebrew** (may prompt for your macOS password):

```bash
brew install --cask miniforge
```

Then wire it into the shell:

```bash
"$HOME/miniforge3/bin/conda" init zsh
```

🧍 **You must open a new terminal after this** for `conda` to be on your PATH. (Agents can keep using
the absolute path `$HOME/miniforge3/bin/conda` without restarting anything.)

### Step 2 — Create the environment

```bash
conda create -n pravaah python=3.11 -y
```

**Python 3.11 specifically.** 3.12/3.13 have thinner coverage for `numba`/`pysheds`; 3.9 is too old.
3.11 is the sweet spot where everything in this stack is known-good on arm64.

### Step 3 — The conda-forge block (compiled / geospatial / numeric)

```bash
conda install -n pravaah -c conda-forge -y \
  numpy pandas scipy pyarrow dask \
  xarray zarr netcdf4 \
  gdal rasterio fiona pyproj shapely geopandas rioxarray \
  pysheds osmnx scikit-image numba \
  scikit-learn lightgbm shap \
  matplotlib folium boto3 requests pyyaml \
  jupyterlab ipykernel
```

> ⚠️ **`pysteps` is NOT on conda-forge** — verified 31 Aug 2026, `conda search`
> returns no match for any platform. It goes in the pip block. (An earlier draft of this
> document claimed otherwise; the install failed and this is the correction.)

### Step 4 — The pip block (pure-Python; run **after** step 3, never before)

```bash
conda run -n pravaah pip install \
  fastapi "uvicorn[standard]" pydantic python-dotenv \
  streamlit streamlit-folium \
  openmeteo-requests requests-cache retry-requests \
  imdlib earthengine-api ecmwf-opendata \
  anthropic
```

> ⚠️ **`pip` is all-or-nothing.** One package failing to build means *none* of the batch
> installs. Keep `pysteps` (the only package that compiles from source) out of this
> command so a pysteps failure cannot block the other 13 packages.

### Step 4b — `pysteps` (compiles from source; needs OpenMP)

**The failure you will hit:** `clang: error: unsupported option '-fopenmp'`.
Apple's clang ships without OpenMP support, and pysteps passes `-fopenmp` unconditionally.
The fix is to build with conda-forge's clang, which has it:

```bash
conda install -n pravaah -c conda-forge -y llvm-openmp clang clangxx compiler-rt

ENVP="$HOME/miniforge3/envs/pravaah"
conda run -n pravaah env \
  CC="$ENVP/bin/clang" CXX="$ENVP/bin/clang++" \
  CFLAGS="-I$ENVP/include" LDFLAGS="-L$ENVP/lib -Wl,-rpath,$ENVP/lib" \
  pip install pysteps
```

**If this still fails, do not burn time on it.** `pysteps` is needed only for the
nowcast baseline (P5-T3) and the animation frames. It blocks nothing in P0–P4, and the
baseline can fall back to persistence + a simple optical-flow extrapolation. Ship without
it rather than losing an hour.

### Step 5 — Verify

`scripts/env_check.py` imports every library and prints its version. **Phase 0 does not close until
every line is ✅** — including `pysheds`, `pysteps`, `rasterio`, `geopandas`, `numba`, `lightgbm`.

---

## 4. Who does what — agent vs you

| Task | Who | Why |
|---|---|---|
| Download + run the Miniforge installer | 🤖 **Agent** | Non-interactive with `-b -p`; no password needed |
| `conda init zsh` | 🤖 **Agent** | But 🧍 **you must open a new terminal** for it to affect *your* shell |
| `conda create` / `conda install` / `pip install` | 🤖 **Agent** | Absolute paths work; no shell state needed |
| Run `env_check.py`, diagnose failures | 🤖 **Agent** | This is exactly the kind of loop to delegate |
| **`earthengine authenticate`** | 🧍 **YOU — mandatory** | Opens a browser, needs your Google login and your GEE project id. An agent cannot and should not do this. |
| **Create `.env` with API keys** | 🧍 **YOU — mandatory** | Never hand credentials to an agent. Agents write `.env.example` only. |
| `npm create vite` / `npm install` | 🤖 **Agent** | Standard, non-interactive |
| Approve anything that prompts for your macOS password | 🧍 **YOU** | Avoidable if we use the `-b -p` installer path |

**Short version:** an agent can do the entire install. The only two things that are genuinely yours
are **GEE authentication** and **the API keys**.

---

## 5. React ↔ FastAPI — the wiring that usually goes wrong

Two servers in development, one server in production. The trick is to make **the frontend code
identical in both cases**.

### Development (two processes)

```
Vite dev server  :5173   ← you open this in the browser
FastAPI          :8000   ← serves /api/*
```

**Do NOT solve this with CORS middleware.** Use the **Vite dev proxy** instead — `ui/vite.config.js`:

```js
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': 'http://localhost:8000' }
  }
})
```

### Production (one process)

```bash
cd ui && npm run build          # → ui/dist
uvicorn serve.main:app          # FastAPI mounts ui/dist at "/"
```

```python
# serve/main.py — mount LAST, after all /api routes are registered
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="ui/dist", html=True), name="ui")
```

### Why this specific arrangement

Because the frontend **always** calls `fetch('/api/wards')` — a relative path — in both modes. In dev
the Vite proxy forwards it; in production it's the same origin. **The code never changes, CORS never
exists, and the airplane-mode test passes for free.** If you use absolute URLs plus CORS middleware
instead, you get a CORS bug in dev, a different bug in production, and a broken offline build.

**Two gotchas:**
- Mount `StaticFiles` **after** the `/api` routes, or it swallows them.
- `html=True` makes client-side routing (`/command`, `/inundation`) fall back to `index.html`.
  Without it, a page refresh on any route 404s.

---

## 6. Google Earth Engine — treat as optional, not blocking

⚠️ GEE on the Community tier is **slow to export** and needs interactive auth. On a one-day clock it
is a real schedule risk. **Every GEE layer we need has a credential-free direct-download path.**

| Layer | GEE collection | Direct alternative (prefer this) |
|---|---|---|
| Landcover / impervious | `ESA/WorldCover/v200` | AWS Open Data bucket `esa-worldcover` (unsigned S3) |
| Population | `WorldPop/GP/100m/pop` | `hub.worldpop.org` — direct GeoTIFF for India, 100 m |
| Built-up | GHSL | JRC direct tile download (`ghsl.jrc.ec.europa.eu`) |
| Permanent water | `JRC/GSW1_4` | Global Surface Water direct tile download |
| Satellite rain | `NASA/GPM_L3/IMERG_V07` | **Not needed for v0.** ERA5 via Open-Meteo is the training target and needs no key. |

**Plan:** kick off GEE auth and the 28 Jun 2024 IMERG export early because it's free to have running
in the background — but **build against the direct paths**, and let IMERG be an enhancement that
lands if it lands.

> Per charter rule **R6**: fetch one file from each of these URLs and inspect the real response
> *before* writing the parser. Bucket paths and tile-naming schemes change.

---

## 7. Other traps worth knowing about up front

| Trap | Prevention |
|---|---|
| **Node 25 is very new.** Some packages declare `engines` ranges that stop at 22 → warnings, occasionally a hard failure. | Warnings are fine, ignore them. If `npm install` genuinely fails: `brew install node@22` and use that for `ui/` only. |
| **Overpass / osmnx rate-limits** and can be slow or briefly ban you. | Pull **once**, cache the raw response to `data/raw/`, never re-pull in a loop. Same for Open-Meteo — turn on `requests-cache`. |
| **CRS misalignment** — the silent killer. Rasters at different resolutions, in different projections, silently "aligning" to garbage. | Pick **one** CRS and **one** 100 m transform in `cube/grid.py`, derive everything from it, and assert alignment after every resample. Most P2 bugs are this. |
| **Timezones.** Open-Meteo can return local time; IMD reports IST; satellite is UTC. | **UTC internally, always** (charter R8). Convert to IST only in the UI. Set `"timezone": "UTC"` on every Open-Meteo call. |
| **Memory on the 100 m grid** (~560k cells × event-hours). | Subsample negatives; process per event window; use dask/chunked xarray rather than loading everything. |
| **`.env` leaking into git.** | `.gitignore` it in P1-T1, before the key exists. Commit `.env.example` only. |
| **Loggers stopping when the Mac sleeps.** | `caffeinate -is` in the logger's terminal, and check `health_check.py` morning and night. |
| **Jupyter using the wrong interpreter.** | `conda run -n pravaah python -m ipykernel install --user --name pravaah` and select that kernel explicitly. |

---

## 8. Notebooks vs scripts — the rule

- **Data pulls → always scripts.** Long-running, must be resumable and cacheable. A kernel dying at
  pull 47 of 56 is a self-inflicted wound.
- **Modelling logic → lives in modules** (`features/`, `models/`), not in cells.
- **Notebooks → thin.** They `import` from those modules, call them, and plot. You get the
  interactive loop *and* the code is already in its final home.

> **If you'd be upset when the kernel dies, it's a script.**
