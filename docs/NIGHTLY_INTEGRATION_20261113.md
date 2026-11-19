# Nightly fixes ready for review — 2026-11-13

This delivery publishes three previously local fixes without reimplementing,
cherry-picking or rewriting their commits. It is stacked on PR15
(`integrate/immution-completion-20261110`, `291fe59`), which depends on PR14.
The original completion checklist remains historical evidence for its scope.

| Preserved commit | Completed change | Regression coverage |
| --- | --- | --- |
| `76f9a70` | Filter gate CSV rotation names before the candidate cap | Unrelated backups cannot hide valid rotations; true cap remains visible |
| `66d7122` | Normalize IPv4-mapped aliases before hashing gate CSV addresses | Unique-IP counts, unchanged events, rotations/Hosts/actions, native/compatible/NAT64 IPv6 remain distinct |
| `388c2a9` | Strict CSV parsing and clean failure in standalone bandwidth estimator | Oversized fields, unclosed quotes, no partial estimate, valid quoted/multiline input |

## Verification provenance

Each fix has synthetic failing-before/passing-after evidence in its original
development delivery. Local source verification already completed on the chain:

- 99 dashboard tests, including PTY navigation/resize/terminal restoration,
  on `66d7122`; the following commit does not change dashboard files.
- 60 core/CLI tests and release check on `388c2a9`.
- 3 synthetic cross-component pipeline tests on `388c2a9`.

This integration adds only documentation to that exact code tree. It does not
repeat those completed local suites. Hosted `tests` and `ubuntu-integration`
must succeed on the newly published head before treating it as CI-green;
the publication receipt/PR checks, not predecessor checks, establish that.
No release gate is marked complete merely because a workflow exists.

## Remaining backlog and limits

- [x] Preserve all three local fixes and their original SHAs in one reviewable branch.
- [x] Document the dependency and verification provenance rather than recoding fixes.
- [ ] Review and authorize promotion of the PR14 -> PR15 -> nightly-fixes stack.
- [ ] Reconcile bases and exact-head checks after any authorized downstack change.
- [ ] Separately authorize deployment; PR publication is not installation.
- [ ] Supply the operational evidence required by [the release checklist](RELEASE_CHECKLIST.md).

The gate CSV selector keeps its existing lexicographic order; this follow-up
does not add numeric/date ordering guarantees there. The separate traffic-log
numeric ordering already belongs to PR15. Read/file/event budgets, privacy,
ASCII layout, scoring, gate policy, logging schema and runtime configuration
are unchanged. Unique IPs remain overlapping counts, not people or bots.
Strict CSV syntax does not authenticate records or validate every schema field.

No main merge, force push, tag, production access, service/config/scheduler
change or rollout is part of this delivery. Review the incremental diff against
PR15, not only the cumulative diff against main.

## Follow-up priority update — 2026-11-17

1. Completed in a separate stacked candidate: reject duplicate CSV headers and
   records whose cell count differs from the header in the standalone bandwidth
   estimator. Previously these could silently drop events or use a shifted URI.
   Error output remains generic, nonzero and without a partial estimate. Valid
   quoted/multiline CSV and legacy missing-action handling remain unchanged.
   Three synthetic malformed structures failed before and pass after; all ten
   bandwidth tests pass. Source release checks pass (61 core/CLI tests).
2. Review PR14 -> PR15 -> PR16 and this follow-up; reconcile exact-head CI after
   any base change. No merge, deployment or operational evidence is implied.
3. Completed in stacked test-clock candidate: freeze datetime.now() as well as
   time.time() in test_existing_scoring_identical_with_monitor_enabled, retaining
   full JSON equality (including reason timestamps). Deterministic advancing-clock
   reproduction fails before the fix; focused integration suite passes afterward.
   Original observation: one local
   release run crossed a wall-clock second between engines and differed only in
   reason timestamps; an unchanged retry passed. This is a test-clock issue,
   not evidence of a scoring or bandwidth regression.
4. Existing monitor/proxy/privacy/release evidence gates remain open. Daily
   visits remain estimated browser-like visits, never exact human counts.

No dependencies, scoring, runtime permissions, enforcement, license or data
visibility changes. The estimator only reads synthetic/local inputs; this
verification used no production logs. Hosted checks must pass on the exact new
head; historical green runs are not substituted.

## Follow-up priority update — 2026-11-19

1. New stacked candidate on PR18 corrects `--action all` bandwidth output:
   the combined total includes monitor-mode hypothetical savings, not solely
   prevented traffic. Show blocked/would_block counts separately and label the
   total combined actual/potential; default and monitor-only modes unchanged.
   Synthetic mixed and monitor-only regressions fail before/pass after.
2. Review PR14–18 and this candidate, reconcile bases/checks after downstack
   changes. No merge or deployment authority is implied.
3. Operational monitor/proxy/privacy/release evidence remains outstanding;
   synthetic tests cannot satisfy those gates. No Nov19 scheduled receipt was
   present when this slice began; Nov18 verified PR18's 16 successful checks.
