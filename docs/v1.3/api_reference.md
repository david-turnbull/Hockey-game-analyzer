# PuckLens v1.3 RESTful API Reference

## 1. Season Analytics Endpoints

### `GET /api/seasons`
Returns all distinct regular seasons available in the database.

**Response (200 OK):**
```json
{
  "count": 2,
  "seasons": ["20242025", "20232024"]
}
```

---

### `GET /api/seasons/<season>/teams`
Returns analytical metrics and rankings for all teams in a given season.

**Query Parameters:**
- `situation` (optional, string): `all` (default), `5v5`, `pp`, `sh`

**Response (200 OK):**
```json
{
  "season": "20242025",
  "situation": "all",
  "team_count": 32,
  "teams": [
    {
      "team_id": 20,
      "team_abbrev": "CGY",
      "team_name": "Calgary Flames",
      "gp": 25,
      "w": 13,
      "l": 9,
      "otl": 3,
      "pts": 29,
      "gf": 74,
      "ga": 70,
      "goal_diff": 4,
      "cf": 1420,
      "ca": 1380,
      "cf_pct": 50.71,
      "ff": 1050,
      "fa": 1010,
      "ff_pct": 50.97,
      "xgf": 76.4,
      "xga": 72.1,
      "xg_pct": 51.45,
      "xgf_per_60": 3.01,
      "xga_per_60": 2.84,
      "gf_xgf_diff": -2.4,
      "ga_xga_diff": -2.1,
      "xg_diff": 4.3,
      "rankings": {
        "xg_pct_rank": 12,
        "xgf_per_60_rank": 10,
        "xga_per_60_rank": 15,
        "cf_pct_rank": 14,
        "ff_pct_rank": 13,
        "gf_xgf_diff_rank": 18
      }
    }
  ]
}
```

---

### `GET /api/teams/<team_id>/season/<season>`
Returns detailed season performance for a specific team, including both all-situations and 5v5 splits.

**Query Parameters:**
- `situation` (optional, string): `all` (default), `5v5`, `pp`, `sh`

---

### `GET /api/teams/<team_id>/season/<season>/trends`
Returns chronological rolling trends for a team across multiple window sizes (5, 10, 20 games).

**Response (200 OK):**
```json
{
  "team_id": 20,
  "season": "20242025",
  "windows": {
    "5": [
      {
        "game_number": 5,
        "game_id": 2024020080,
        "date": "2024-10-22",
        "opponent": "EDM",
        "rolling_xg_pct": 54.2,
        "rolling_cf_pct": 52.8,
        "rolling_xgf_per_60": 3.25,
        "rolling_xga_per_60": 2.74,
        "rolling_xg_diff": 2.55,
        "rolling_finishing_diff": 0.45
      }
    ]
  }
}
```

---

### `GET /api/teams/<team_id>/season/<season>/players`
Returns season skater statistics for all skaters on a team roster.

---

### `GET /api/teams/<team_id>/season/<season>/goalies`
Returns season goaltender statistics for all goaltenders on a team roster.

---

### `GET /api/players/<player_id>/season/<season>`
Returns individual counting stats, rates per 60, and 5v5 on-ice possession metrics for a skater.

**Query Parameters:**
- `include_trends` (optional, bool): If `true`, attaches rolling 5-game performance series.

---

### `GET /api/goalies/<goalie_id>/season/<season>`
Returns goaltender workload, actual save %, Expected Goals Against ($xGA$), and Goals Saved Above Expected ($GSAx$).

**Query Parameters:**
- `include_trends` (optional, bool): If `true`, attaches rolling 5-game performance series.

---

### `GET /api/seasons/<season>/leaders`
Returns analytical leaderboards with configurable metrics and minimum sample thresholds.

**Query Parameters:**
- `category`: `skaters` (default) or `goalies`
- `metric`: e.g. `xg`, `goals_above_expected`, `points`, `gsax`, `save_pct`
- `min_gp`: Minimum games played threshold (default: 1)
- `min_toi`: Minimum ice time seconds threshold (default: 0)
- `min_unblocked`: Minimum unblocked attempts threshold (skaters)
- `min_shots`: Minimum shots faced threshold (goalies)
- `limit`: Result count cap (default: 50)

---

## 2. Model Explainability Endpoints

### `GET /api/shots/<shot_id>/xg-explanation`
Returns mathematical feature contribution decomposition and logit factor breakdown for an unblocked shot attempt.

**Response (200 OK):**
```json
{
  "shot_id": "2024020080105",
  "shooter_name": "Mikael Backlund",
  "team_abbrev": "CGY",
  "period": 2,
  "period_time": "14:22",
  "shot_type": "Wrist",
  "outcome": "Goal",
  "distance": 18.4,
  "angle": 12.1,
  "strength_state": "5v5",
  "xg": 0.1425,
  "logit": -1.794,
  "intercept": -2.645,
  "raw_odds": 0.1662,
  "baseline_probability": 0.0666,
  "odds_multiplier": 2.33,
  "positive_factors": [
    {
      "feature_name": "Distance to Net",
      "raw_value": 18.4,
      "coefficient": -0.048,
      "contribution": 0.85
    }
  ],
  "negative_factors": [
    {
      "feature_name": "Shot Angle",
      "raw_value": 12.1,
      "coefficient": -0.015,
      "contribution": -0.18
    }
  ]
}
```

**Blocked Shot Error (400 Bad Request):**
```json
{
  "error": "Blocked shot attempts are excluded from expected goals (xG = NULL) in accordance with PuckLens domain rules."
}
```
