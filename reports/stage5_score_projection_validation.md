# Stage 5 Score Projection Model Validation Report

## Executive Summary
- **Win Model Status**: Frozen `v1.4.0` (SHA: `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`)
- **Production Score Model Recommendation**: **`POISSON`**
- **Rationale**: Independent Poisson remains the production score model. Although Negative Binomial achieves a statistically significant NLL reduction on both evaluation seasons ($CI < 0$), the gain is microscopic ($\Delta \text{NLL} \approx -0.0005$) and does not improve MAE, residual bias, or calibration enough to justify additional complexity.

## Frozen Candidate Parameter Estimation (2021-22 to 2023-24 Training Set)
- Loaded from frozen artifact `models/forecasting/score_candidate_params_v1.4.0.json` (3,936 training games).
- **Independent Poisson**: Baseline ($\lambda_h, \lambda_a$).
- **Negative Binomial**: $\alpha = 0.001$ (Observed goal dispersion ratio $Var/Mean \approx 0.90..0.98$, confirming slight under-dispersion; NB overdispersion $\alpha$ floored near 0).
- **Bivariate Poisson**: $\lambda_3 = 0.001$ (Observed residual goal covariance $\approx 0$).
- **Dixon-Coles Adjustment**: $\gamma = 0.0543$ (Exploratory low-score tie adjustment).

## Shootout Target & Anomaly Resolution
- **2024-25 Shootouts**: 77 / 1,312 games (5.9%). Anomalies after subtracting 1 winner goal: **0**.
- **2025-26 Shootouts**: 119 / 1,312 games (9.1%). Anomalies after subtracting 1 winner goal: **0**.
- Subtracting 1 shootout goal from the winning team correctly restores exact ties (`reg_home == reg_away`) for 100% of shootout games.

## Summary Metrics Comparison (Regulation + OT Hockey Goals Target)

### 2024-25 Season (1,312 games)
| Model | Total MAE | Res Bias | Res Std | Exact Top-1 | Exact Top-5 | Joint NLL | Pre-SO LogLoss | Pre-SO Brier | 6.0 Line Acc (Push Excl) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `poisson` | 2.0659 | -0.2446 | 2.5807 | 4.42% | 19.51% | 4.0658 | 0.9608 | 0.5867 | 51.23% |
| `neg_binomial` | 2.0659 | -0.2446 | 2.5807 | 4.42% | 19.51% | 4.0653 | 0.9604 | 0.5865 | 51.23% |
| `bivariate_poisson` | 2.0659 | -0.2446 | 2.5807 | 4.42% | 19.51% | 4.0659 | 0.9608 | 0.5867 | 51.23% |
| `dixon_coles` | 2.0659 | -0.2446 | 2.5807 | 4.42% | 19.66% | 4.0651 | 0.9585 | 0.5860 | 51.23% |

### 2025-26 Season (1,312 games)
| Model | Total MAE | Res Bias | Res Std | Exact Top-1 | Exact Top-5 | Joint NLL | Pre-SO LogLoss | Pre-SO Brier | 6.0 Line Acc (Push Excl) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `poisson` | 2.0587 | -0.4800 | 2.5299 | 3.73% | 17.91% | 4.0343 | 1.0035 | 0.6169 | 53.27% |
| `neg_binomial` | 2.0587 | -0.4800 | 2.5299 | 3.73% | 17.99% | 4.0338 | 1.0031 | 0.6168 | 53.27% |
| `bivariate_poisson` | 2.0587 | -0.4800 | 2.5299 | 3.73% | 17.84% | 4.0343 | 1.0035 | 0.6170 | 53.27% |
| `dixon_coles` | 2.0587 | -0.4800 | 2.5299 | 3.73% | 17.91% | 4.0332 | 1.0024 | 0.6167 | 53.27% |

### Pooled 2024-25 & 2025-26 (2,624 games)
| Model | Total MAE | Res Bias | Res Std | Exact Top-1 | Exact Top-5 | Joint NLL | Pre-SO LogLoss | Pre-SO Brier | 6.0 Line Acc (Push Excl) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `poisson` | 2.0623 | -0.3623 | 2.5582 | 4.08% | 18.71% | 4.0501 | 0.9822 | 0.6018 | 52.25% |
| `neg_binomial` | 2.0623 | -0.3623 | 2.5582 | 4.08% | 18.75% | 4.0496 | 0.9818 | 0.6017 | 52.25% |
| `bivariate_poisson` | 2.0623 | -0.3623 | 2.5582 | 4.08% | 18.67% | 4.0501 | 0.9822 | 0.6018 | 52.25% |
| `dixon_coles` | 2.0623 | -0.3623 | 2.5582 | 4.08% | 18.79% | 4.0492 | 0.9804 | 0.6013 | 52.25% |

## Paired Bootstrap 95% Confidence Intervals (vs Independent Poisson)

| Candidate Model | 2024-25 NLL Diff 95% CI | 2025-26 NLL Diff 95% CI | Decision Status |
| :--- | :---: | :---: | :--- |
| `neg_binomial` | [-0.00076, -0.00040] | [-0.00066, -0.00029] | Statistically significant NLL improvement on BOTH seasons, but gain is microscopic (delta NLL ~ -0.0005) and does not improve MAE/bias enough to justify model complexity. |
| `bivariate_poisson` | [0.00000, 0.00005] | [0.00002, 0.00005] | No statistically significant improvement over Poisson. |
| `dixon_coles` | [-0.00269, 0.00208] | [-0.00221, -0.00005] | Improvement on ONE season only (insufficient to replace Poisson). |

## Official Boxscore Target vs Regulation + OT Hockey Goals
Comparing projections against official boxscore scores (which include the +1 shootout goal bonus) vs true regulation+OT hockey goal totals:

| Target Definition | Poisson Total MAE (2024-25) | Poisson Total MAE (2025-26) | Residual Bias (2024-25) | Residual Bias (2025-26) |
| :--- | :---: | :---: | :---: | :---: |
| Regulation + OT Hockey Goals | 2.0659 | 2.0587 | -0.2446 | -0.4800 |
| Official Boxscore Scores | 2.0595 | 2.0519 | -0.1859 | -0.3893 |

**Shootout Bias Interpretation**: Evaluating against true regulation + OT hockey goals reveals a larger negative residual bias (-0.2446 in 2024-25, -0.4800 in 2025-26) compared to unadjusted boxscore scores (-0.1859 in 2024-25, -0.3893 in 2025-26). This proves that the +1 shootout winner goal bonus in boxscore totals was **partially masking score-model overprediction**.