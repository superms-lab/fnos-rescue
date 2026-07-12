# Versioning and releases

FNOS Rescue follows Semantic Versioning.

- `MAJOR`: incompatible CLI, case schema, or plugin protocol changes after 1.0.
- `MINOR`: backward-compatible features or new filesystem plugins.
- `PATCH`: fixes, documentation, safety checks, and compatible helper improvements.

During `0.x`, the project is alpha and may change quickly. Case schema changes must include an
explicit migration or a clear compatibility error.

## Release checklist

1. Update the version in `pyproject.toml` and `src/fnos_rescue/__init__.py`.
2. Move entries from `Unreleased` into the dated release section in `CHANGELOG.md`.
3. Run unit tests, compileall, package build, and secret/path scans.
4. Commit the release, tag it as `vMAJOR.MINOR.PATCH`, and push the tag.
5. GitHub Actions builds wheel and source archives and creates or updates the GitHub Release.
6. Never publish raw cases, images, caches, or unredacted logs in a release.

Run `ALLOW_DIRTY=1 ./scripts/release-preflight.sh` while preparing a release, then run it again
without `ALLOW_DIRTY` after the release commit. The clean-worktree run is the actual release gate.
