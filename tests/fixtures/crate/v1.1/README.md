# crate v1.1 golden fixtures

Never regenerate, never edit, never delete. `tests/python/crate_import/test_s0_seams.py` pins the sha256 of
`SHA256SUMS`, so an edited fixture fails. v1.1 added the `project` home, plugin homes, three roles, one member and one
manifest key (`docs/crate-format.md`, section 11).

Written once by:

    venv/bin/python3 -m tests.python.cplugs.crate.golden_build_v11 --write tests/fixtures/crate/v1.1

The world is the v1 golden world (`golden_build.py`) plus a project folder of files and a synthetic plugin `synth`
that keeps boards and drafts, with the clock (1792267200), install id, machine label, app version and bundle
ids injected.

- `project-own.crate`: project, own, codec zstd
- `session-own.crate`: session, own, codec lzma

Beside each crate: `<file>.sha256`. `expected/<file>.json` is what each crate lists; `expected/coverage.json` the vocabulary.
