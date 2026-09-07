# Expected Goals (xG) Model Explainability & Factor Decomposition

## Mathematical Foundation
PuckLens employs a calibrated Logistic Regression classifier to evaluate shot danger. A primary advantage of logistic regression is its strict mathematical interpretability.

Given a feature vector $\mathbf{x} = [x_1, x_2, \dots, x_M]^T$, the model computes the log-odds (logit) of a goal as an affine combination of weights $\mathbf{w}$ and intercept $b$:
$$\text{logit}(\mathbf{x}) = b + \sum_{k=1}^{M} w_k \cdot x_k$$

The final Expected Goals probability $xG$ is obtained via the logistic sigmoid function:
$$xG = \sigma(\text{logit}(\mathbf{x})) = \frac{1}{1 + e^{-\text{logit}(\mathbf{x})}}$$

## Feature Contribution Decomposition
Each feature's linear contribution to the total logit is defined as:
$$c_k = w_k \cdot x_k$$

### 1. Danger-Increasing Factors ($c_k > 0$)
Features that raise the log-odds of a goal above the model baseline:
- Short distance to net (e.g. inner slot, crease rebounds).
- Low shot angle relative to net center.
- Favorable attacking strength state (e.g. 5v4 power play).
- Rapid sequence / short elapsed time following a previous play-by-play event.

### 2. Danger-Reducing Factors ($c_k < 0$)
Features that diminish the log-odds of a goal:
- Long distance to net (e.g. point shots, neutral zone dumps).
- Sharp / acute shot angle (e.g. goal-line attempts).
- Shorthanded penalty-killing strength state (e.g. 4v5).

## Baseline Comparison & Odds Multiplier
To provide immediate context to coaches and analysts:
- **Baseline Probability ($p_{\text{base}}$):** The empirical league average conversion rate for unblocked shots ($6.66\%$).
- **Baseline Odds:**
  $$\text{odds}_{\text{base}} = \frac{p_{\text{base}}}{1 - p_{\text{base}}}$$
- **Shot Odds:**
  $$\text{odds}_{\text{shot}} = \frac{xG}{1 - xG} = e^{\text{logit}}$$
- **Odds Multiplier:**
  $$\text{Multiplier} = \frac{\text{odds}_{\text{shot}}}{\text{odds}_{\text{base}}}$$
  A multiplier of $3.5\times$ indicates the shot is $3.5$ times more dangerous than the typical unblocked NHL attempt.

## Blocked Shot Rejection
In accordance with PuckLens domain invariants, blocked shot attempts are barred from receiving an xG explanation. Requesting `/api/shots/<shot_id>/xg-explanation` on a blocked shot returns an HTTP 400 Bad Request.
