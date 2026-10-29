# Extension contract schemas

JSON Schema (draft 2020-12) for the Carnivore Extension Contract 1.0. Read `docs/extension-contract.md` first.

- `item.schema.json` is L0, the base every item extends (the `carnivore.json` sidecar).
- `<kind>.schema.json` is L1 for `cplug`, `widget`, `theme`, `skill`, `claude-code-plugin`, `mod` and `loadout`. Each is `allOf` L0 plus the kind's own rules, closed with `unevaluatedProperties: false`.

- `warez/` is L2, the public front door: `warez/item.schema.json` (the base overlay) and `warez/<kind>.schema.json` per kind, each `allOf` its L1 file, the overlay and the kind's tightening. A `$ref` resolves relative to the referring file.
- The whole folder's `*.json` files are pinned by one digest, `src/cplugs/sdk/schema_digest.py` (`SCHEMA_SET_DIGEST`); the catalog repo vendors a byte-identical copy. After a schema change run `python3 -m src.cplugs.sdk.schema_digest` and update the constant and the catalog pin.

They live under `src/` because the packaged app ships `src/` and not a top-level `schemas/` folder. The app reads them with the stdlib checker `src/cplugs/sdk/schema_check.py`, which refuses any keyword it does not apply: a new schema may use only the keywords listed in that module. `tests/python/cplugs/test_extension_schemas.py` proves the layering, every refusal and the catalog vectors.

`data` (base, required for a `cplug`) declares the stores an item keeps; its cross-field rules (unique ids, a `root_setting` the plugin declares) are in `src/cplugs/sdk/data_decl.py`. See `docs/extension-contract.md` section 8.

## `warez/policy.json`

The one policy file for the public front door; plain JSON with stable keys, read by the hosted catalog API (`hosted/catalog/api/submit_policy.py`, staged by its `deploy.sh`, sha256 pinned in `tests/hosted_catalog/test_submit_limits.py`) and by the gate runner (`scripts/warez_gates/policy.py`). It is inside the schema set digest, so changing it moves `SCHEMA_SET_DIGEST`.

- `version`: integer, 1.
- `kinds`: object, kind name (`skill`, `theme`, `claude-code-plugin`, `mod`, `loadout`, `cplug`, `widget`) to `"open"` (any signed-in account may submit), `"first_party"` (only the first-party handles) or `"closed"` (nobody). An unlisted kind is closed.
- `first_party_handles`: list of handles that publish first-party items (`carnivore`, `external`); also reserved against submission in `src/models/catalog_names.py` (`RESERVED_PUBLISHER_HANDLES`).
- `approvers`: list of GitHub logins that may approve and override.
- `licenses`: list of accepted SPDX license identifiers.
