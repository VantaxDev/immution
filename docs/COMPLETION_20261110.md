# Immution completion candidate — 2026-11-10

## Inventory and finite delivery

Inventory at start: main `e0a64c225fffada55376c15993ad111d25cf0a80`, no open
GitHub issues, PRs 5–13 merged. PR14 remained draft at
`897d341a153c5736e16dc9621469bd81c83264c7` with successful checks.
The repository has no separate roadmap: RELEASE_CHECKLIST.md, MAINTAINERS.md,
DASHBOARD_VISITS.md and historical verification notes describe the backlog.
Historical open-PR statements in dated notes are not current blockers.

The implementation scope for this completion is deliberately finite:

- [x] Preserve and integrate PR14's traffic-first dashboard, actual renderer demo,
      site/day rollups and conservative browser-group semantics.
- [x] Integrate local `26515af` (nonnegative bandwidth assumptions), `9761b1d`
      (CSV error handling), `99189ca` (malformed URI privacy). Originals remain
      preserved; integration commits are `30db2a2`, `0102327`, `88107eb`.
- [x] Fix lexicographic rotation priority: `.2` must precede `.10` under budget.
- [x] Fix the file-cap selection: retain active + lowest numeric suffixes rather
      than an arbitrary directory prefix. Resolve .N/.N.gz overlap before cap.
- [x] Expose source-scoped issue names in the traffic viewport, or explain the
      8 MiB prefix limit and possibly omitted recent records when capped.
- [x] Add synthetic failing-before/passing-after regressions and run local gates.
- [ ] Promote a reviewed, CI-green candidate to main (separate merge decision).
- [ ] Deploy this follow-up (separate operational decision; not part of coding).

Publication uses a follow-up stacked on PR14, preserving its existing commits
and checks. Review both layers; the follow-up alone does not replace PR14.
No scoring, gate, engine, policy, log-format or runtime configuration change.
No dependency added: existing stdlib parser and renderer suffice for these bugs.

## Reproduction and verification

Three new regressions FAIL against the integrated pre-fix implementation:
rotation `.10` consumes the budget before `.2`; file-cap selection depends on
directory iteration; the viewport omits the read-cap explanation/issue names.
All three PASS after the patch.

Final local code verification:

- `./scripts/check-release.sh`: PASS, including 58 core tests, Python compilation,
  every shell file, PHP syntax and PHP gate smoke, fixture config and systemd unit.
- `python3 -m unittest discover -s experimental/dashboard -v`: 91 PASS, including
  real local synthetic PTY navigation/resize/terminal restoration and privacy,
  no-clobber export, DST/ranges, gzip and source-safety regressions.
- `node experimental/dashboard/test_ui.cjs`: PASS.
- `git diff --check`: PASS.

Hosted `tests` and `ubuntu-integration` must pass on the exact published head;
local source tests do not establish old-runtime or live Apache integration.
See the PR's checks for exact SHA-bound Python/PHP matrices and disposable
Apache/lifecycle pipeline results. No production access or real logs used.

## Honest remaining boundaries

The 8 MiB decompressed budget, 100000 event cap, 32 files/site and 128 total
files remain unchanged. Prefix reads can omit recent records. Numeric suffix
priority is a logrotate convention, not a guarantee of event-time ordering.
The scan is still metadata-discovered and content-bounded, not continuous
history. UNKNOWN remains mandatory; any detected issue means INCOMPLETE.
No human-count claim, extrapolation or silent unbounded read is introduced.
Redacted/missing User-Agent data cannot be recovered by changing software.

Release gates are not independent coding tasks to invent evidence for:

1. Representative five-day monitor evidence and review of legitimate paths /
   exclusions (including rotations) are not established by these tests.
2. Proxy/CDN identity agreement requires matched operational evidence where used.
3. Private vulnerability reporting was read-only verified **disabled** on
   2026-11-10; enabling it is a repository-setting decision, not performed here.
4. Live website performance claims need separate verification; repository copy
   is not evidence of the current deployed site.
5. A stable tag/archive must come from a reviewed green release commit after
   applicable human gates. No tag, merge or deployment is performed here.

Load/cardinality measurements, general DDoS protection, PHP-FPM support,
continuous traffic history and authenticated human/crawler identities are
outside this finite bug-fix delivery; existing documented limits still apply.
