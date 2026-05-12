"""
Group-level VIF directly from events/ and tsv/ (no GLM fitting).
- Rebuilds the same design matrix as surfaceGLM.py for every run of every subject
- Computes VIF for the 4 task regressors of interest per run
- Averages VIF across runs within subject, then aggregates across subjects
  (mean, SD, SEM, 95% CI via t-distribution, df = n-1)
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from nilearn.glm.first_level import make_first_level_design_matrix

# =========================
# Settings
# =========================
TR = 1.4
n_volumes = 319
frame_times = np.arange(n_volumes) * TR
motion_columns = ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]

# Design matrix is built with all 4 task regressors (no event-level merging).
# Columns in alphabetical order of trial_type:
#   0: PFace    -> Face Perception
#   1: PScene   -> Scene Perception
#   2: TestResp -> Test (ignored)
#   3: WMFace   -> Face WM
#   4: WMScene  -> Scene WM
target_idx = [0, 1, 3, 4]
target_labels = ["Face Perception", "Scene Perception", "Face WM", "Scene WM"]

# Pool every (subject, run, face/scene) VIF value into one distribution per category.
# No averaging: all observations are treated as samples of the same distribution.
#   Perception distribution = {Face Perception, Scene Perception} across all (sub, run)
#   WM         distribution = {Face WM,         Scene WM}         across all (sub, run)
pool_groups = {
    "Perception": ["Face Perception", "Scene Perception"],
    "WM": ["Face WM", "Scene WM"],
}

subject_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]


def build_run_list(sub: int):
    """Return (ses, run) tuples in event-file sequential order."""
    if sub == 9:
        run_counts = {1: 8, 2: 8, 3: 7, 4: 9}
    elif sub == 3:
        run_counts = {1: 8}  # only ses-01 available
    else:
        run_counts = {1: 8, 2: 8, 3: 8, 4: 8}
    return [(ses, r) for ses, n in run_counts.items() for r in range(1, n + 1)]


def compute_vif(X: np.ndarray, idx_list):
    """VIF for selected columns of X by regressing on the rest."""
    vif = np.zeros(len(idx_list))
    for j, ti in enumerate(idx_list):
        y = X[:, ti]
        Xo = np.delete(X, ti, axis=1)
        beta, *_ = np.linalg.lstsq(Xo, y, rcond=None)
        yhat = Xo @ beta
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        vif[j] = 1.0 / (1.0 - r2) if r2 < 1.0 else np.inf
    return vif


# =========================
# Per-subject run-mean VIF
# =========================
cwd = Path.cwd()
event_dir = cwd / "event"
tsv_dir = cwd / "tsv"
out_dir = cwd / "design_matrix"
out_dir.mkdir(parents=True, exist_ok=True)

long_rows = []  # one row per (sub, run, target)
for sub in subject_ids:
    runs = build_run_list(sub)
    n_used = 0
    for i, (ses, run) in enumerate(runs, start=1):
        ev_path = event_dir / f"event_sub{sub}_run{i}.csv"
        ts_path = tsv_dir / f"sub-0{sub}_ses-0{ses}_task-prm_run-{run:02d}_desc-confounds_timeseries.tsv"
        if not ev_path.exists() or not ts_path.exists():
            print(f"  [skip] sub{sub} run{i}: missing {ev_path.name} or {ts_path.name}")
            continue

        events = pd.read_csv(ev_path)
        motion = pd.read_csv(ts_path, sep="\t")[motion_columns].values

        dm = make_first_level_design_matrix(
            frame_times,
            events,
            hrf_model="spm",
            drift_model="polynomial",
            drift_order=3,
            add_regs=motion,
            add_reg_names=motion_columns,
        )
        vif_vals = compute_vif(dm.values, target_idx)
        for lbl, v in zip(target_labels, vif_vals):
            long_rows.append({"sub": sub, "run": i, "regressor": lbl, "VIF": v})
        n_used += 1
    print(f"sub{sub}: {n_used} runs processed")

long_df = pd.DataFrame(long_rows)

# =========================
# Pooled distribution per category (no averaging across sub/run/face-scene)
# =========================
records = []
for new_lbl, src_lbls in pool_groups.items():
    vals = long_df.loc[long_df["regressor"].isin(src_lbls), "VIF"].values.astype(float)
    n = len(vals)
    mean = vals.mean()
    sd = vals.std(ddof=1)
    sem = sd / np.sqrt(n)
    tcrit = stats.t.ppf(0.975, df=n - 1)
    ci_low = mean - tcrit * sem
    ci_high = mean + tcrit * sem
    records.append(
        {
            "category": new_lbl,
            "n": n,
            "mean": mean,
            "SD": sd,
            "SEM": sem,
            "CI95_low": ci_low,
            "CI95_high": ci_high,
            "median": np.median(vals),
            "min": vals.min(),
            "max": vals.max(),
        }
    )

group_df = pd.DataFrame(records).set_index("category")

print(f"\nPooled VIF distribution (every sub × run × face/scene as a sample):")
print(group_df.round(3))
print("\nSummary:")
for lbl, row in group_df.iterrows():
    print(f"  {lbl:<12s}: n={int(row['n'])}, mean={row['mean']:.3f}  "
          f"[95% CI {row['CI95_low']:.3f}, {row['CI95_high']:.3f}]  "
          f"SD={row['SD']:.3f}")

long_df.to_csv(out_dir / "VIF_all_observations.csv", index=False)
group_df.to_csv(out_dir / "VIF_group_summary_pooled.csv")
print(f"\nSaved: {out_dir / 'VIF_all_observations.csv'}")
print(f"Saved: {out_dir / 'VIF_group_summary_pooled.csv'}")
