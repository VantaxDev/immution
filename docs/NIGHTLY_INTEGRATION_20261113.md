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
