# Move rc3 into the existing private repository

The uploaded ZIP contained a valid two-commit Git repository whose remote is on
the owner's private Git service. Preserve that history; do not publish the
original ZIP or its `.git` directory as a release download.

From a clean clone of the private repository:

```bash
git status
git switch -c release/v0.1.0-rc3
git rm -r .
```

Copy the contents of the reviewed `immution-v0.1.0-rc3/` directory into the
repository root, then run:

```bash
git add .
git status
./scripts/check-release.sh
git commit -m "Prepare Immution 0.1.0 rc3"
```

Review the resulting commit before pushing the branch. Merge it only after the
automated and human gates in `docs/RELEASE_CHECKLIST.md` pass.
