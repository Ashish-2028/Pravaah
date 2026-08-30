#!/usr/bin/env python
"""
PRAVAAH — the automated no-look-ahead proof (BUILD_PLAN P3-T9, charter R4).

This is the executable answer to the hardest judge question:
"How do you know there's no data leakage?"

    "Every forecast row keeps issue_time; the cube has exactly one read path
     returning the latest data issued at or before t0; an automated test
     shuffles future rows and asserts the features are unchanged; splits are
     by event and year, never random."

Everything after the semicolons is checked here. Run it in CI, run it before
the demo, and run it after ANY change to the cube or the accessor.

    python eval/leakage_tests.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cube.accessor import TARGET_COLS, Cube  # noqa: E402
from cube.grid import split_of  # noqa: E402

T0 = "2024-06-28T04:00:00Z"          # mid-event: the moment the demo pauses on
RNG = np.random.default_rng(20240628)


def _report(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def test_shuffle_future(cube: Cube) -> bool:
    """
    THE CORE TEST. Corrupt every row issued after t0 — shuffle the values,
    scramble them, make them garbage — then read at t0 again. If a single
    feature changes, the future leaked into the past.
    """
    before = cube.at(T0)
    t0 = pd.Timestamp(T0)

    poisoned = cube.df.copy()
    future = poisoned.issue_time > t0
    n_future = int(future.sum())

    num_cols = [c for c in poisoned.columns
                if pd.api.types.is_numeric_dtype(poisoned[c]) and c not in ("lat", "lon")]
    for c in num_cols:
        vals = poisoned.loc[future, c].to_numpy(copy=True)
        RNG.shuffle(vals)
        poisoned.loc[future, c] = vals * -999.0     # scramble AND corrupt

    after = Cube(poisoned).at(T0)

    same_shape = before.shape == after.shape
    if not same_shape:
        return _report("shuffle-future", False,
                       f"shape changed {before.shape} -> {after.shape}")

    cmp_cols = [c for c in before.columns if c in num_cols]
    identical = all(
        before[c].equals(after[c])
        or np.allclose(before[c].to_numpy(dtype=float),
                       after[c].to_numpy(dtype=float), equal_nan=True)
        for c in cmp_cols
    )
    return _report("shuffle-future",
                   identical,
                   f"{n_future:,} future rows corrupted, {len(cmp_cols)} cols compared, "
                   f"snapshot {before.shape[0]:,} rows unchanged")


def test_no_future_issue_times(cube: Cube) -> bool:
    """Nothing returned by at(t0) may have been issued after t0. The direct check."""
    snap = cube.at(T0)
    t0 = pd.Timestamp(T0)
    bad = int((snap.issue_time > t0).sum())
    return _report("no-future-issue-times", bad == 0, f"{bad} violating rows")


def test_valid_vs_issue_is_a_real_distinction(cube: Cube) -> bool:
    """
    Guard against a false sense of security. If issue_time were just a copy of
    valid_time everywhere, the accessor would be filtering on nothing and this
    whole suite would pass vacuously. At least the NWP-bearing rows must show
    the two stamps genuinely differing somewhere.
    """
    df = cube.df
    stamps = [c for c in df.columns if c.startswith("nwp_issue_time")]
    if not stamps:
        return _report("issue_time-is-meaningful", False, "no forecast issue stamps at all")
    differs = sum(int((df[c] != df.valid_time).sum()) for c in stamps)
    # And prove the gating actually BITES: at t0 some NWP cells must be blanked
    # that are non-null in the raw cube.
    t0 = pd.Timestamp(T0)
    snap = cube.at(T0)
    raw = df[(df.issue_time <= t0) & (df.issue_time >= t0 - pd.Timedelta(hours=72))]
    col = "precipitation_gfs_seamless"
    bites = (col in snap.columns
             and int(raw[col].notna().sum()) > int(snap[col].notna().sum()))
    return _report("issue_time-is-meaningful", differs > 0 and bites,
                   f"{len(stamps)} forecast stamps, {differs:,} rows differ from valid_time; "
                   f"gating blanks {int(raw[col].notna().sum()) - int(snap[col].notna().sum())} "
                   f"future-issued NWP cells at t0")


def test_targets_excluded_from_features(cube: Cube) -> bool:
    """The answer key must not be reachable through feature_columns()."""
    feats = cube.feature_columns()
    leaked = [c for c in TARGET_COLS if c in feats]
    return _report("targets-not-features", not leaked, f"leaked: {leaked}" if leaked else
                   f"{len(feats)} features, targets held out")


def test_splits_are_temporal(cube: Cube) -> bool:
    """
    Charter R5: splits by year, never random. TRAIN must end before VAL starts
    and VAL before TEST — no interleaving, which is what a random split does.
    """
    df = cube.df
    ok = True
    bounds = {}
    for name in ("train", "val", "test"):
        s = df[df.split == name]
        if s.empty:
            ok = False
            bounds[name] = "EMPTY"
            continue
        bounds[name] = (s.valid_time.min(), s.valid_time.max())
    if ok:
        ok = (bounds["train"][1] < bounds["val"][0]
              and bounds["val"][1] < bounds["test"][0])
    detail = " | ".join(
        f"{k}:{str(v[0])[:10]}..{str(v[1])[:10]}" if isinstance(v, tuple) else f"{k}:{v}"
        for k, v in bounds.items())
    return _report("splits-temporal-not-random", ok, detail)


def test_split_assignment_is_pure(cube: Cube) -> bool:
    """Every row's split must match what grid.split_of() says for its timestamp."""
    s = cube.df.sample(min(20000, len(cube.df)), random_state=0)
    mismatch = int((s.valid_time.map(split_of) != s.split).sum())
    return _report("split-labels-consistent", mismatch == 0,
                   f"{mismatch} mismatches in {len(s):,} sampled rows")


def main() -> int:
    print("=" * 70)
    print(f"PRAVAAH leakage tests   (t0 = {T0})")
    print("=" * 70)
    cube = Cube.load()
    print(f"  {cube!r}\n")

    results = [
        test_no_future_issue_times(cube),
        test_shuffle_future(cube),
        test_valid_vs_issue_is_a_real_distinction(cube),
        test_targets_excluded_from_features(cube),
        test_splits_are_temporal(cube),
        test_split_assignment_is_pure(cube),
    ]

    print("=" * 70)
    if all(results):
        print(f"ALL {len(results)} LEAKAGE TESTS PASS — the honesty law holds")
        return 0
    print(f"{results.count(False)} of {len(results)} FAILED — DO NOT TRAIN ON THIS CUBE")
    return 1


if __name__ == "__main__":
    sys.exit(main())
