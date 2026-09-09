# Minimum Sample Threshold Standards

## Overview
Small sample sizes generate extreme outlier rates in hockey analytics (e.g. a fourth-line forward with 1 goal on 1 shot boasting a 100% conversion rate or a backup goaltender with 1 save on 1 shot boasting a 1.000 Save %). PuckLens v1.3 implements configurable, domain-informed sample thresholds across all leaderboards and service endpoints.

## Canonical Thresholds

### 1. Skater Season Analytics
- **`min_gp` (Minimum Games Played):**
  Filters out call-ups or emergency injury replacements (Default: `1` for team rosters, `5` for league leaderboards).
- **`min_toi_seconds` (Minimum Time on Ice):**
  Ensures sufficient 5v5 or overall observation time (Default: `0` seconds for rosters, `3000` seconds [50 minutes] for rate leaderboards).
- **`min_unblocked_attempts` (Minimum Unblocked Shots):**
  Applies to individual shooting percentage ($Sh\%$) and expected conversion rate ($Exp\ Conv\%$) to eliminate single-shot distortion (Default: `10` unblocked attempts).

### 2. Goaltender Season Analytics
- **`min_gp` (Minimum Games Played):**
  Excludes emergency backup goaltenders (Default: `1` for team rosters, `3` for league leaderboards).
- **`min_shots_faced` (Minimum Shots Faced):**
  Ensures sample stability for save percentage and $GSAx/60$ comparisons (Default: `50` shots faced for leaderboards).
- **`min_toi_seconds` (Minimum Time on Ice):**
  Default: `3600` seconds (60 minutes / 1 full game).

## API & UI Query Parameters
All threshold parameters can be passed dynamically via API query parameters:
```http
GET /api/seasons/20242025/leaders?category=skaters&metric=xg&min_gp=5&min_toi=3000&min_unblocked=15
GET /api/seasons/20242025/leaders?category=goalies&metric=gsax&min_gp=3&min_shots=50
```
