# Standalone bandwidth estimate: CSV parser failures

`tools/immution_bandwidth.py` now uses the existing standard-library CSV reader
in strict mode. An unterminated quoted field no longer silently discards the
damaged tail and produces a plausible estimate from earlier rows. CSV parser
errors, including the unchanged default field-size limit, exit with status 1
and `cannot parse events CSV; bandwidth estimate not produced` on stderr.
No estimate is printed, even if valid events preceded the failing record.
The diagnostic includes no source path, raw record or traceback.

Valid quoted commas, doubled quotes and multiline fields remain supported.
Action selection, byte assumptions, fallback values and input files are
unchanged. This is syntax validation, not a new event schema or proof that a
syntactically valid row is complete or authentic. In particular, existing
handling of absent/unrecognized actions is unchanged. A concurrently written
partial quoted record may fail this one-shot read; retry after the writer
finishes rather than accepting a partial estimate.

Synthetic CLI regressions cover an oversized field and an unclosed quote after
a valid blocked event (both fail before the fix), plus a valid quoted/multiline
record and unchanged source bytes. Verification commands:

```sh
./scripts/check-release.sh
python3 -m unittest discover -s tests/acceptance -p pipeline_compatibility.py -v
git diff --check
```

This standalone command is separate from the previously fixed `immutionctl.py
report` parser. No scoring, gate, dashboard, CSV schema, installer or service
change is involved. Local results do not replace hosted compatibility CI.
