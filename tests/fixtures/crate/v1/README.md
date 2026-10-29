# crate v1 golden fixtures

Never regenerate, never edit, never delete. A new minor version gets its own folder (`v1.1/`).
`tests/python/crate_format/test_golden_v1.py` pins the sha256 of `SHA256SUMS`, so an edited fixture fails.

Written once by:

    venv/bin/python3 -m tests.python.cplugs.crate.golden_build --write tests/fixtures/crate/v1

The world is the inventory test world (`tests/python/inventory/world_build.py`) plus
`tests/python/cplugs/crate/golden_extras.py`, built in a fresh temporary folder, with the clock
(1792267200), install id, machine label, app version and bundle ids injected.

The test key is not committed: the identity is X25519 secret = sha256 of the seed in
`tests/python/crate_format/golden_read.py`, bech32 encoded by `crate_crypto.keys.encode_identity`.

- `session-own.crate`: session, own, codec lzma
- `project-own.crate`: project, own, codec zstd
- `project-share.crate`: project, share, codec zstd
- `session-own.crate.age`: session, own, codec default, encrypted to the test recipient

Beside each crate: `<file>.sha256`; beside the encrypted one, its README sidecar.
`expected/<file>.json` is what each crate lists; `expected/coverage.json` the vocabulary they use.
