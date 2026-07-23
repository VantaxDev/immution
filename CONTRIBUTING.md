# Contributing

Bug reports, focused pull requests, tests and documentation improvements are
welcome.

Before opening a pull request:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/immution.py tools/*.py
bash -n scripts/*.sh
```

Keep each change small and explain its effect on false positives, runtime
permissions and reversibility. New scoring rules require:

1. a documented signal and point value;
2. a regression test for malicious behaviour;
3. a regression test for a plausible legitimate request;
4. monitor-mode evidence before default block-mode use is considered.

Never submit production logs or personal data. Use the anonymized fixtures and
documentation-only network ranges.
