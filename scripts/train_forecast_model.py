import os
import sys
import json
import argparse
import logging
import subprocess
from datetime import datetime, timezone

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.analytics.forecasting.win_probability import WinProbabilityModel
from app.analytics.forecasting.model_registry import ForecastModelRegistry
from scripts.audit_seasons import audit_season_data

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")
logger = logging.getLogger("train_forecast_model")

def get_git_commit_sha() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"

def main():
    parser = argparse.ArgumentParser(description="PuckLens Production Forecast Model Training Utility")
    parser.add_argument("--train-season", default="20212022", help="Season for candidate parameter fitting")
    parser.add_argument("--select-season", default="20222023", help="Season for model selection criterion")
    parser.add_argument("--calibrate-season", default="20232024", help="Season for probability calibration")
    parser.add_argument("--excluded-holdout", default="20242025", help="Holdout season excluded from training")
    parser.add_argument("--version", default="v1.4.0", help="Model version tag (e.g. v1.4.0)")
    parser.add_argument("--output-dir", default=None, help="Directory to store model artifact and manifest")
    parser.add_argument("--force", action="store_true", help="Bypass production data gate check")
    args = parser.parse_args()

    output_dir = args.output_dir or os.path.join(project_root, "models", "forecasting")
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 70)
    print(f" PuckLens Production Forecast Model Training ({args.version})")
    print("=" * 70)

    app = create_app('development')
    with app.app_context():
        # 1. Audit Production Data Gate
        audit_summary = audit_season_data(app)
        gate = audit_summary.get("production_forecast_data_gate", {})
        if not gate.get("pass", False) and not args.force:
            reasons = "; ".join(gate.get("reasons", ["Production gate failed"]))
            logger.error(f"PRODUCTION FORECAST TRAINING BLOCKED: {reasons}")
            print(f"\nERROR: Production forecast training blocked by data gate:\n  - {reasons}")
            print("\nUse --force to bypass this safety gate for testing purposes.")
            sys.exit(1)

        # 2. Execute Multi-Phase Training Protocol
        model = WinProbabilityModel()
        summary = model.train_and_select(
            train_season=args.train_season,
            select_season=args.select_season,
            calibrate_season=args.calibrate_season,
            skip_gate=args.force
        )

        # 3. Save Model Pickle Artifact
        pkl_path = os.path.join(output_dir, f"pucklens-win-{args.version}.pkl")
        model.save_model(pkl_path)

        # Legacy location save for backward compatibility
        legacy_pkl_path = os.path.join(project_root, "app", "analytics", "forecasting", f"win_model_{args.version}.pkl")
        model.save_model(legacy_pkl_path)

        # 4. Calculate SHA-256 Checksum
        sha256_hash = ForecastModelRegistry.compute_sha256(pkl_path)

        # 5. Build Metadata Manifest
        git_sha = get_git_commit_sha()
        
        # Sample counts
        X_train, _, _ = model.extract_features_and_targets(args.train_season)
        X_select, _, _ = model.extract_features_and_targets(args.select_season)
        X_calib, _, _ = model.extract_features_and_targets(args.calibrate_season)

        train_samples = len(X_train) + len(X_select)
        calib_samples = len(X_calib)

        manifest = model.generate_metadata_manifest(
            artifact_sha256=sha256_hash,
            train_season=args.train_season,
            select_season=args.select_season,
            calibrate_season=args.calibrate_season,
            excluded_holdout=args.excluded_holdout,
            train_samples=train_samples,
            calib_samples=calib_samples,
            git_sha=git_sha
        )
        manifest["model_version"] = args.version

        # 6. Save Metadata Manifest JSON
        json_path = os.path.join(output_dir, f"pucklens-win-{args.version}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print("\n" + "-" * 70)
        print(" Model Artifact & Manifest Generation Summary")
        print("-" * 70)
        print(f"  Model Version:       {manifest['model_version']}")
        print(f"  Selected Model:      {manifest['model_architecture']}")
        print(f"  Artifact File:       {pkl_path}")
        print(f"  Manifest File:       {json_path}")
        print(f"  SHA-256 Checksum:    {sha256_hash}")
        print(f"  Training Samples:    {train_samples}")
        print(f"  Calibration Samples: {calib_samples}")
        print(f"  Git Commit SHA:      {git_sha}")
        print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
