# PuckLens v1.4 — Stage 5 Score Projection Validation Methodology

## Overview
Stage 5 evaluates the `PoissonScoreModel` as a separate modeling component of the PuckLens forecasting platform. While the win probability classifier models the overall game winner probability ($P(\text{Home Win})$) and remains strictly frozen at `v1.4.0` (SHA-256: `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`), the score model projects joint goal distributions $P(H=h, A=a)$ for regulation + overtime hockey play.

This document details the mathematical formulations, target resolution rules, adaptive matrix support, candidate models, and empirical evaluation results.

---

## 1. Score Model Candidates & Reproducible Parameter Freezing

All candidate model parameters were estimated strictly using the training seasons **2021-22 through 2023-24 (3,936 regular-season games)** via `scripts/fit_score_candidate_models.py` and saved to `models/forecasting/score_candidate_params_v1.4.0.json`. **Zero parameter tuning or fitting** was performed on the 2024-25 holdout season or the 2025-26 external validation season.

### Candidate 1: Independent Poisson Baseline (Production Model)
Assume home and away goals are independent Poisson random variables:
$$P(H=h, A=a) = \frac{\lambda_h^h e^{-\lambda_h}}{h!} \cdot \frac{\lambda_a^a e^{-\lambda_a}}{a!}$$

### Candidate 2: Negative Binomial Model
Models potential goal over-dispersion using overdispersion parameter $\alpha$:
$$\text{Var}[X] = \mu + \alpha \mu^2$$
Using training data (2021-22..2023-24), observed home goal mean = 3.074 (var = 2.777) and away goal mean = 2.816 (var = 2.755). Because variance is slightly below mean (dispersion ratio $\approx 0.90 - 0.98$), hockey goals exhibit slight under-dispersion rather than over-dispersion. The standard over-dispersion parameter is floored at $\alpha = 0.001$, rendering Negative Binomial virtually identical to Independent Poisson.

### Candidate 3: Bivariate Poisson / Shared-Intensity Correlation Model
Models goal correlation between teams via a shared intensity component $\lambda_3$:
$$X_1 = Y_1 + Y_3, \quad X_2 = Y_2 + Y_3 \quad \text{where } Y_1 \sim \text{Poisson}(\lambda_h - \lambda_3), Y_2 \sim \text{Poisson}(\lambda_a - \lambda_3), Y_3 \sim \text{Poisson}(\lambda_3)$$
Empirical training set residual covariance $\text{Cov}(e_h, e_a) \approx 0.000$, yielding $\lambda_3 = 0.001$.

### Candidate 4: Dixon-Coles Low-Score Adjustment
Applies an exploratory multiplicative adjustment $\tau(h, a; \gamma)$ to low scorelines (0-0, 1-0, 0-1, 1-1):
$$\tau(0,0) = 1 - \lambda_h \lambda_a \gamma$$
$$\tau(1,0) = 1 + \lambda_a \gamma$$
$$\tau(0,1) = 1 + \lambda_h \gamma$$
$$\tau(1,1) = 1 - \gamma$$
$$\tau(h,a) = 1 \quad \text{otherwise}$$
Estimated on training data via NLL minimization: $\gamma = 0.0543$.

---

## 2. Shootout Target Resolution & Anomaly Auditing

Official NHL boxscore game scores include a +1 goal bonus awarded to the winner of a shootout. Because the score model projects hockey goals scored during regulation and overtime play (where shootouts are unplayed skills competitions), evaluating projections against official boxscore scores introduces a systematic +1 goal offset on shootout games (~6-9% of regular season games).

### Resolution Rule
1. Shootout detection: Check if any play-by-play event in `Event` has `period_type == 'SO'`.
2. For non-shootout games: `reg_home_goals = box_home`, `reg_away_goals = box_away`.
3. For shootout games: Subtract exactly 1 goal from the winning team:
   - If `box_home > box_away`: `reg_home = box_home - 1`, `reg_away = box_away`
   - If `box_away > box_home`: `reg_home = box_home`, `reg_away = box_away - 1`
4. Consistency Check & Anomaly Reporting: Assert `reg_home_goals == reg_away_goals` for 100% of shootout games. Any violation is logged as an anomaly.

### Shootout Bias Interpretation
Evaluating against true regulation + OT hockey goals reveals a larger negative residual bias (-0.2446 in 2024-25, -0.4800 in 2025-26) compared to unadjusted boxscore scores (-0.1859 in 2024-25, -0.3893 in 2025-26). This proves that the +1 shootout winner goal bonus in boxscore totals was **partially masking score-model overprediction**.

---

## 3. Pre-Shootout 3-Class Outcome Formulation

Pre-shootout game outcomes are evaluated as a 3-class probability distribution with explicit outcome field names:
1. **`home_win_probability_pre_shootout`** ($h > a$): $P(\text{Home Win}) = \sum_{h > a} P(h, a)$
2. **`away_win_probability_pre_shootout`** ($a > h$): $P(\text{Away Win}) = \sum_{a > h} P(h, a)$
3. **`shootout_required_probability`** ($h = a$): $P(\text{Tie}) = \sum_{h = a} P(h, a)$

*(Legacy regulation-named fields `home_win_probability_regulation`, `away_win_probability_regulation`, `regulation_tie_probability` are preserved as backward-compatibility aliases.)*

---

## 4. Genuinely Adaptive Matrix Support (Tolerance < 1e-8)

To fix score-matrix truncation errors present in fixed grids, `PoissonScoreModel.generate_joint_matrix()` dynamically expands grid size $N \times N$ adaptively until omitted probability mass $1.0 - \sum_{h=0}^{N-1} \sum_{a=0}^{N-1} P(h, a) < 1e-8$ across all expected goal inputs ($\lambda \in [0.8, 6.5]$).

For display and UI responses, a $10 \times 10$ slice is extracted separately as `score_matrix`.

---

## 5. Model Selection Criteria & Decision Rationale

An alternative model replaces Independent Poisson **ONLY IF** it satisfies all of the following conditions:
1. Demonstrates statistically significant out-of-sample improvement on **BOTH** 2024-25 and 2025-26 evaluation seasons (paired bootstrap 95% CI upper bound < 0 for NLL difference).
2. Provides a practically meaningful improvement in total goal MAE or residual bias.
3. Maintains numerical stability and calibration across all games.

### Recommendation & Rationale
Independent Poisson is retained as the production score model. Although Negative Binomial achieves a statistically significant NLL reduction on both evaluation seasons ($CI < 0$), the gain is microscopic ($\Delta \text{NLL} \approx -0.0005$) and provides zero practical improvement in MAE, residual bias, or calibration to justify additional model complexity.
