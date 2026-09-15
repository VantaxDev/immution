# Update the public repository without replacing its history

The public repository is https://github.com/VantaxDev/immution.
Do not copy `.git`, upload a source ZIP as the repository, force-push, or merge
unrelated histories. Use a clean clone or your existing clean checkout.

For this review, apply the supplied patch on a branch:

```bash
git status --short
git switch -c review/immution-2026-09-15
git apply --check /path/to/immution-review-e6d9ce5.patch
git apply /path/to/immution-review-e6d9ce5.patch
./scripts/check-release.sh
git add -A
git diff --cached --check
git commit -m "Review state lifecycle, installation and maintainer instructions"
git push -u origin review/immution-2026-09-15
```

Start only with a clean checkout. The patch is based on e6d9ce5; if the check
fails, stop and compare later changes rather than forcing it. Inspect staged
changes before committing. Require both workflows green before merging.
Do not exclude `*.log` when copying source: tests/fixtures/access.log is
synthetic test data and must be included. Exclude actual production logs.
