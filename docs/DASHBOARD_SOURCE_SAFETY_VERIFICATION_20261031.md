# Dashboard source safety verification — 2026-10-31

## Reproduction and change

A FIFO supplied as an active CSV source or named like a gzip rotation blocks
refresh indefinitely while opening it, before the byte budget can apply. A
synthetic subprocess regression hit its three-second deadline on unchanged
main (858aa998); the subprocess is killed and reaped by the test runner.

Discovery now skips nonregular files with a source-number-only warning. Every
new input is opened nonblocking and its actual descriptor checked with fstat,
so replacing a discovered regular file with a FIFO cannot bypass the check.
Rejected descriptors close immediately. Gzip wraps the same checked input;
the reader explicitly owns and closes both wrapper and underlying descriptor.
Regular symlink targets remain allowed. Existing stdlib os/stat/gzip facilities
suffice; no dependency or custom polling service is introduced.

## Evidence

- 45 dashboard tests PASS, including PTY, rotations, gzip corruption, timeframe,
  exports, a real FIFO subprocess deadline, opened-inode rejection and cleanup.
- 14 core tests PASS via scripts/check-release.sh; PHP smoke/syntax,
  configuration, compilation, shell and systemd verification PASS.
- node experimental/dashboard/test_ui.cjs PASS; git diff --check PASS.
- No production logs or access needed. Tests use temporary synthetic fixtures.

## Boundaries

Only experimental dashboard reader, its tests and docs change. No scoring,
gate, configuration, scheduler, website, or service changes. This branch starts
from main independently of PR #5; it neither includes nor replaces the pending
Host privacy fixes. No merge/deploy is performed or authorized here.

This prevents special-file open hangs, not arbitrary filesystem stalls. Byte
budgets are not wall-clock deadlines. Existing retention, copytruncate,
cardinality and history UNKNOWN limitations still apply. Release human gates
remain pending. Hosted CI results belong to the exact published head and must
be checked separately from this local evidence.
