#!/usr/bin/env python
"""
PRAVAAH — Phase 0 exit gate.

Imports every library the project depends on and prints its version.
BUILD_PLAN.md P0 does not close until every line is OK.

    conda run -n pravaah python scripts/env_check.py
"""
from __future__ import annotations

import importlib
import platform
import sys

# (import name, pip/conda name, why we need it)
CHECKS: list[tuple[str, str, str]] = [
    # --- numeric core
    ("numpy",        "numpy",             "everything"),
    ("pandas",       "pandas",            "tabular cube"),
    ("scipy",        "scipy",             "stats"),
    ("pyarrow",      "pyarrow",           "parquet"),
    ("dask",         "dask",              "out-of-core arrays"),
    # --- gridded storage
    ("xarray",       "xarray",            "the fusion cube"),
    ("zarr",         "zarr",              "cube store"),
    ("netCDF4",      "netcdf4",           "IMERG / GEE exports"),
    # --- geospatial (the fragile block)
    ("rasterio",     "rasterio",          "DEM + raster IO"),
    ("fiona",        "fiona",             "vector IO"),
    ("pyproj",       "pyproj",            "CRS transforms"),
    ("shapely",      "shapely",           "geometry ops"),
    ("geopandas",    "geopandas",         "spatial joins, exposure"),
    ("rioxarray",    "rioxarray",         "raster <-> xarray"),
    ("osmnx",        "osmnx",             "OSM drains + assets"),
    ("skimage",      "scikit-image",      "raster morphology"),
    # --- hydrology + nowcasting (numba-backed, most likely to break)
    ("numba",        "numba",             "pysheds JIT"),
    ("pysheds",      "pysheds",           "HAND / flow accumulation"),
    ("pysteps",      "pysteps",           "nowcast baseline + animation"),
    # --- ML
    ("sklearn",      "scikit-learn",      "isotonic calibration, metrics"),
    ("lightgbm",     "lightgbm",          "all three v0 models"),
    ("shap",         "shap",              "per-ward drivers"),
    # --- plotting / misc
    ("matplotlib",   "matplotlib",        "reports/*.png"),
    ("folium",       "folium",            "streamlit maps"),
    ("boto3",        "boto3",             "unsigned S3 (DEM, NOAA)"),
    ("requests",     "requests",          "http"),
    ("yaml",         "pyyaml",            "aoi config"),
    # --- serving
    ("fastapi",      "fastapi",           "backend"),
    ("uvicorn",      "uvicorn",           "asgi server"),
    ("pydantic",     "pydantic",          "the file contracts"),
    ("dotenv",       "python-dotenv",     ".env"),
    ("streamlit",    "streamlit",         "validation harness + fallback"),
    ("streamlit_folium", "streamlit-folium", "map in the harness"),
    # --- data clients
    ("openmeteo_requests", "openmeteo-requests", "A1/A2/A3 pulls"),
    ("requests_cache",     "requests-cache",     "never re-pull"),
    ("imdlib",             "imdlib",             "A11 IMD gridded"),
    ("ee",                 "earthengine-api",    "A4-A6 (optional for v0)"),
    ("ecmwf.opendata",     "ecmwf-opendata",     "A16 live NWP"),
    ("anthropic",          "anthropic",          "advisory layer"),
]


def main() -> int:
    print("=" * 68)
    print("PRAVAAH environment check")
    print(f"python   {sys.version.split()[0]}  ({platform.machine()})")
    print(f"exe      {sys.executable}")
    print("=" * 68)

    failures: list[tuple[str, str, str]] = []
    for mod, pkg, why in CHECKS:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "")
            if not ver:
                top = importlib.import_module(mod.split(".")[0])
                ver = getattr(top, "__version__", "?")
            print(f"  OK   {mod:<22} {ver:<12} {why}")
        except Exception as exc:  # noqa: BLE001 - we want every failure, not the first
            print(f"  FAIL {mod:<22} {'':<12} {why}")
            failures.append((mod, pkg, f"{type(exc).__name__}: {exc}"))

    print("=" * 68)
    if failures:
        print(f"{len(failures)} of {len(CHECKS)} FAILED — Phase 0 is NOT complete\n")
        for mod, pkg, err in failures:
            print(f"  {mod}  (install: {pkg})")
            print(f"      {err}")
        return 1

    # Functional smoke tests: importing is not the same as working.
    print("functional smoke tests")
    try:
        import numpy as np
        import lightgbm as lgb
        import geopandas as gpd
        from pysheds.grid import Grid  # noqa: F401
        from shapely.geometry import Point

        X = np.random.rand(200, 4)
        y = (X[:, 0] + X[:, 1] > 1.0).astype(int)
        lgb.train({"objective": "binary", "verbose": -1}, lgb.Dataset(X, y), 5)
        print("  OK   lightgbm trains")

        g = gpd.GeoDataFrame(geometry=[Point(77.22, 28.65)], crs="EPSG:4326")
        assert abs(g.to_crs("EPSG:32643").geometry.x.iloc[0]) > 0
        print("  OK   geopandas + pyproj reproject (4326 -> UTM 43N)")

        print("  OK   pysheds Grid imports (numba JIT available)")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL functional test: {type(exc).__name__}: {exc}")
        return 1

    print("=" * 68)
    print(f"ALL {len(CHECKS)} LIBRARIES OK — Phase 0 gate GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
