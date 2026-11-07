# Explicit action evidence in bandwidth estimates

## Reproduction and fix

The estimator defaulted an absent CSV `action` column to `blocked`. A historical
or malformed CSV containing only `request_uri` consequently claimed blocked
traffic without evidence. `--action all` additionally counted blank and unknown
actions, including `allowed`.

Use only the exact gate actions `blocked` and `would_block`. Missing, empty,
unknown and differently cased actions are excluded in every selection mode.
`all` is the union of the two recognized actions, not every CSV row. Legacy
files without action evidence now produce zero eligible events. This is a
conservative compatibility change, not a claim that such requests were allowed.

Five synthetic CLI tests run the real tool with temporary CSV/access files and
verify input bytes remain unchanged. Before the fix, four regression assertions
failed (including subtests); valid block and monitor selection already passed.
Afterward all five tests and the full 19-test suite pass on Python 3.6.15,
3.8.20 and 3.12.3. Source release checks pass locally, including PHP 8.3.6 smoke,
Python compilation, Bash syntax, configuration and systemd unit verification.

No dependencies or installer/import changes. No scoring, blocking, dashboard,
config or production changes. This adjusts reporting only: historical medians
and fallback sizes remain estimates. `would_block` and the combined `all` mode
include hypothetical savings, never measured avoided traffic. Public CI is a
separate gate; see the PR checks for exact-commit lifecycle/matrix results.

Run:

```sh
python3 -m unittest discover -s tests -p test_bandwidth.py -v
./scripts/check-release.sh
git diff --check
```
