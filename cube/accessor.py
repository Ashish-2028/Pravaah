"""
PRAVAAH — THE ONE AND ONLY READ PATH INTO THE CUBE (BUILD_PLAN P3-T8).

    Every forecast record keeps BOTH issue_time and valid_time.
    The ONLY read path is cube.at(t0), which returns the latest data
    issued <= t0.                                        — charter rule R4

WHY THIS FILE EXISTS AT ALL
---------------------------
It would be trivially easy, anywhere in this codebase, to write

    df[df.valid_time <= t0]

and quietly train on the future. `valid_time <= t0` is not the same test as
`issue_time <= t0`: a forecast VALID at 04:00 might have been ISSUED at 09:00,
and using it at 04:00 means the model saw tomorrow's newspaper. Scores go up,
the system is worthless, and nothing looks wrong.

So there is exactly one function that reads the cube, it filters on issue_time,
and eval/leakage_tests.py proves it (shuffle every future row, assert the
features at t0 are byte-identical).

This is also the single hardest judge question — "how do you know there's no
leakage?" — and the answer is this file plus that test.

    from cube.accessor import Cube
    c = Cube.load()
    snap = c.at("2024-06-28T04:00Z")        # everything knowable at 04:00 UTC
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CUBE = ROOT / "cube" / "ncr_cube.parquet"

# Columns that describe WHEN/WHERE, not WHAT. Never features.
INDEX_COLS = ["lat", "lon", "valid_time", "issue_time", "date", "split",
              "nwp_issue_time", "nwp_issue_time_prev1",
              "nwp_issue_time_prev2", "nwp_issue_time_prev3"]

# The answer key. Must never appear as a feature at prediction time.
TARGET_COLS = ["precip_obs", "imd_rain_daily"]

# NWP columns published by the same-day run — gated on `nwp_issue_time`.
NWP_SAMEDAY_COLS = [
    "precipitation_ecmwf_ifs025", "precipitation_gfs_seamless",
    "precipitation_icon_seamless", "cape", "convective_inhibition",
    "lifted_index", "nwp_spread", "nwp_mean", "nwp_n_models",
    "d_ecmwf_gfs", "d_ecmwf_icon", "d_gfs_icon",
]
# Columns issued N days before valid_time — each gated on its own stamp.
NWP_PREV_COLS = {
    1: ["precipitation_previous_day1"],
    2: ["precipitation_previous_day2"],
    3: ["precipitation_previous_day3"],
}


@dataclass
class Cube:
    df: pd.DataFrame

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: Path | None = None) -> "Cube":
        p = path or CUBE
        if not p.exists():
            raise FileNotFoundError(f"{p} missing — run cube/build_cube.py")
        df = pd.read_parquet(p)
        for c in ("valid_time", "issue_time"):
            if not pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = pd.to_datetime(df[c], utc=True)
        return cls(df)

    # ------------------------------------------------------- THE READ PATH
    def at(self, t0, lookback_hours: int = 72) -> pd.DataFrame:
        """
        Everything knowable at t0, and nothing else.

        Filters on **issue_time**, never valid_time. A row issued after t0 did
        not exist yet at t0, so it cannot be a feature at t0 — regardless of
        what time it is *about*.

        `lookback_hours` bounds how far back we look; it is a performance
        bound only and cannot admit future data.
        """
        t0 = pd.Timestamp(t0)
        if t0.tzinfo is None:
            t0 = t0.tz_localize("UTC")
        lo = t0 - pd.Timedelta(hours=lookback_hours)

        knowable = self.df[(self.df.issue_time <= t0) & (self.df.issue_time >= lo)].copy()

        # PER-COLUMN GATING. Row-level filtering is not enough: an observation
        # row can be legitimately visible at t0 while the NWP columns attached
        # to that same row come from a run not yet issued. Blank those cells
        # rather than dropping the row — the observation is still knowable.
        if "nwp_issue_time" in knowable.columns:
            future_nwp = knowable["nwp_issue_time"] > t0
            cols = [c for c in NWP_SAMEDAY_COLS if c in knowable.columns]
            knowable.loc[future_nwp, cols] = pd.NA

        for n, cols in NWP_PREV_COLS.items():
            stamp = f"nwp_issue_time_prev{n}"
            if stamp in knowable.columns:
                cols = [c for c in cols if c in knowable.columns]
                if cols:
                    knowable.loc[knowable[stamp] > t0, cols] = pd.NA

        return knowable.sort_values(["lat", "lon", "valid_time"]).reset_index(drop=True)

    def latest_at(self, t0) -> pd.DataFrame:
        """One row per lattice point: the most recent observation known at t0."""
        k = self.at(t0)
        if k.empty:
            return k
        return (k.sort_values("valid_time")
                 .groupby(["lat", "lon"], as_index=False)
                 .tail(1)
                 .reset_index(drop=True))

    # ---------------------------------------------------------------- splits
    def split(self, name: str) -> pd.DataFrame:
        if name not in {"train", "val", "test"}:
            raise ValueError(f"unknown split {name!r}")
        return self.df[self.df.split == name]

    # ------------------------------------------------------------- metadata
    def feature_columns(self) -> list[str]:
        """Every column that is legitimately a feature — index and targets removed."""
        return [c for c in self.df.columns
                if c not in INDEX_COLS and c not in TARGET_COLS]

    def coverage(self) -> pd.Series:
        return (self.df.notna().mean() * 100).round(1)

    def __repr__(self) -> str:
        return (f"<Cube rows={len(self.df):,} "
                f"points={self.df.groupby(['lat','lon']).ngroups} "
                f"{self.df.valid_time.min()} .. {self.df.valid_time.max()}>")
