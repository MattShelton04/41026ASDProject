# Crime observations and coverage

The crime-series product preserves sparse positive observations and explicit coverage, including coverage-only series. A blank can mean observed zero only where the product's blank_means_observed_zero flag is true and the month is inside declared coverage. Outside-coverage months are unavailable, not zero.

Missing coverage is not proof that an offence never occurred. Feature 1 does not calculate crime rates or infer suburb safety from missing observations; interpretation belongs to the owning analytics feature. Keep source period, geography and coverage visible and distinguish null or unavailable evidence from measured zero.

Basis: data-product consumer guide, crime-series product semantics. These are project data-contract rules, not official publisher methodology or a current crime assessment.
