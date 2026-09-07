# Goalie Season Analytics & Quality Metrics

## Overview
Traditional goaltending statistics (Wins, Goals Against Average, and raw Save Percentage) conflate team defensive quality with individual goaltender talent. A goaltender facing high-danger slot rebounds will naturally concede more goals than one facing low-danger perimeter wrist shots. PuckLens v1.3 isolates goaltending skill through Expected Goals Against ($xGA$) and Goals Saved Above Expected ($GSAx$).

## Core Metric Definitions

### 1. Expected Goals Against ($xGA$)
The expected goals against for a goaltender represents the sum of the expected goal probabilities of all unblocked shots on goal faced:
$$xGA = \sum_{s \in \text{Shots Faced}} xG_s$$

### 2. Goals Saved Above Expected ($GSAx$)
Goals Saved Above Expected measures the number of goals prevented relative to an average NHL goaltender facing identical shot quality:
$$GSAx = xGA - GA_{\text{non-empty-net}}$$
- **Positive $GSAx$:** The goaltender has prevented more goals than expected given the danger of shots faced (net positive value).
- **Negative $GSAx$:** The goaltender has allowed more goals than expected (net negative value).

### 3. Standardized Rate ($GSAx/60$)
To compare goaltenders with differing ice times fairly:
$$GSAx/60 = \frac{GSAx}{\text{TOI hours}}$$

### 4. Expected Save Percentage ($Exp\ Sv\%$)
$$Exp\ Sv\% = \frac{\text{Shots Faced} - xGA}{\text{Shots Faced}} \times 100$$
$$Sv\%\ \text{Differential} = \text{Actual } Sv\% - Exp\ Sv\%$$

## Inviolable Domain Rules
1. **Empty-Net Shots Exclusion:**
   When a goaltender is pulled for an extra attacker, any resulting shot attempt or goal is tagged with `empty_net = True`. Empty-net shots are strictly barred from receiving an attribution in the goaltender's $xGA$ or $GSAx$.
2. **Shootout Exclusion:**
   Shootout attempts (`period_type == 'SO'`) do not reflect regulation hockey shot quality and are excluded from season $xGA$ and $GSAx$.
