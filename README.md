# Weighted quantile audit

Version 0.1.0 · Unreleased draft · DOI unassigned

Why does changing the unit of a weight change a quantile? This command-line tool checks a small sample against the boundary-average rule documented for statsmodels `DescrStatsW.quantile`. Save its JSON output to give a colleague the exact calculation and the observed library result. [日本語](README.ja.md)

## Try a two-point sample

Use CPython 3.12.14 on Linux for the bundled replay. Run these commands from the directory containing this README.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -B audit.py examples/two_point_tiny.json > witness.json
python3 -B checker.py witness.json
.venv/bin/python -B replay.py witness.json
```

The sample has values 0 and 2, equal weights of 2⁻³⁵ and probability ¼. The first point carries half the mass, so the exact answer is 0. Statsmodels 0.15.0 returns 1. In `witness.json`, `implementation_diagnosis` is `TOLERANCE_ONLY_WITNESS`. The four certificates agree on 0. The standalone checker prints `"valid": true` and the replay reruns the statsmodels call.

You can also check the [bundled two-point witness](evidence/two_point_tiny.json) using only Python’s standard library.

```sh
python3 -B checker.py evidence/two_point_tiny.json
```

## Known behavior and workaround

Statsmodels compares the target mass with the selected cumulative weight using a fixed absolute tolerance of `1e-10`. In the sample above the gap is 2⁻³⁶. That gap falls within the tolerance, and the implementation returns the mean of 0 and 2. The target, cumulative weights and gap are all exactly representable in this example. [Statsmodels source](https://github.com/statsmodels/statsmodels/blob/v0.15.0/statsmodels/stats/weightstats.py)

For a quantile calculation, normalize positive weights to sum to one before passing them to the library. The following two calls have the same relative weights.

```python
import numpy as np
from statsmodels.stats.weightstats import DescrStatsW

x = [0., 2.]
w = np.array([2.**-35, 2.**-35])
print(DescrStatsW(x, weights=w).quantile([0.25], return_pandas=False))           # [1.]
print(DescrStatsW(x, weights=w / w.sum()).quantile([0.25], return_pandas=False)) # [0.]
```

The [tiny input](examples/two_point_tiny.json) and [normalized input](examples/two_point_normalized.json) give exact reference 0 at either scale. The artificial importance-weight example returns 14 before normalization and 8 afterwards, against exact reference 8. Even at unit total weight, a probability sufficiently close to a boundary can still trigger the tolerance. For example, with equal normalized weights and probability ½ − 2⁻³⁵ the library returns the adjacent mean. [Importance weights](examples/importance_tiny.json) · [Normalized weights](examples/importance_normalized.json)

## Audit your own input

Pass a JSON file to `audit.py` or supply the object on standard input. Use exactly the keys `x`, `w` and `p`. For example, this input uses two equal weights.

```json
{"x":[0,2],"w":["1/2","1/2"],"p":"0.25"}
```

Integers may be JSON numbers. Quote fractions and decimal values to preserve the intended input. Each sample has 1–16 values, strictly positive weights and a probability strictly between zero and one. The limit is 64 KiB, 96 characters per numeric string and 128 bits per reduced numerator or denominator. Decimal exponents range from −128 to 128. Conversion to binary64 must preserve positive weights and an interior probability.

| Field under `axes` | What a true value tells you |
|---|---|
| `definition_difference` | At the binary input, the boundary-average and inverted-CDF definitions give different exact answers. At an exact interior boundary, the former averages adjacent points and the latter selects the lower point. |
| `input_rounding_changes_value` | Converting the supplied rationals to binary64 changes the exact boundary-average answer. |
| `implementation_value_mismatch` | The observed library value differs from the correctly rounded boundary-average answer for the binary input. |

These comparisons can overlap. Each certificate records the bracketing cumulative masses, target mass, selected support and exact answer. The checker uses Python's standard library to recompute the inequalities and formulas. The replay also checks the observed value, recorded Python patch version, dependency versions, and source hashes. [Witness fields](SCHEMA.md) · [Certificate argument](MATHEMATICS.md)

## Reproduce the fixed observations

```sh
bash reproduce.sh --install
```

This installs the locked dependencies, runs the tests and replays the 102 bundled observations (408 certificates). After installation, `bash reproduce.sh` repeats the checks offline. A fresh audit accepts Python 3.12 with the pinned numerical dependencies. Replaying a saved file requires its recorded Python patch version. [Dependency versions](requirements.lock) · [Runtime checks](runtime-lock.json)

## Limits and credits

The audit handles one-dimensional samples and two quantile definitions. It inspects the supplied sample. Hypothesis can search and shrink a failing property separately. A returned value can match several candidate branches (`BRANCH_UNKNOWN`). Diagnostics reconstruct the pinned arithmetic. They can identify a branch only when the observed result distinguishes it from the other candidates. Tests cover finite examples. Exit 0 means the audit completed, including when it found a discrepancy. Invalid or unsupported input exits 2, a runtime mismatch exits 3 and an internal or checker failure exits 4.

The statsmodels developers document the boundary-average convention. NumPy supplies the weighted inverted-CDF comparison. Jeremy Singer-Vine's weightedcalcs and Hypothesis supply scalar comparisons and property-based shrinking used in validating the examples. [Statsmodels quantile](https://www.statsmodels.org/stable/generated/statsmodels.stats.weightstats.DescrStatsW.quantile.html) · [NumPy percentile](https://numpy.org/doc/stable/reference/generated/numpy.percentile.html) · [weightedcalcs](https://pypi.org/project/weightedcalcs/) · [Hypothesis](https://hypothesis.readthedocs.io/)

## AI use and responsibility

OpenAI Codex helped implement the audit and checker, run the comparisons and tests, and draft the documentation. The examples received computational checks and have not undergone human peer review. Tatsuhiko Takimoto takes responsibility for the code, data and conclusions. [Citation](CITATION.cff) · [License](LICENSE)
