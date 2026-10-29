

## 1. The three layers

Each layer is a JSON Schema (draft 2020-12) that `allOf`-extends the one below. The schema is the single source; `tests/fixtures/kind_vectors.json` is its set of test vectors, not a parallel rule set.

| Layer | File | What it pins | Read by |
|---|---|---|---|
| L0 base, every item | `src/schemas/extensions/item.schema.json` | the authored sidecar: `kind`, `id`, `name`, `version`, `api_version`, `min_app_version`, `author`, `license`, `tier`, `scope`, `requires`, `permissions`, `owns` | the plugin parser (`src/cplugs/sdk/sidecar.py`), later the Plugins page, warez install and `carnivore dev validate` |
| L1 per kind | `cplug`, `widget`, `theme`, `skill`, `claude-code-plugin`, `mod`, `loadout` `.schema.json` in the same folder | the kind's own rules, each `allOf` L0 and closed with `unevaluatedProperties: false` | same |

**Where the schemas live.** The brief named `schemas/extensions/`. They sit in `src/schemas/extensions/` instead: the packaged app and the derived server copy ship `src/`, `client/` and `features/` only (`macOS/bootstrap.js` `RESYNC_ALLOWLIST`, `macOS/package.json` `extraResources`), so a top-level `schemas/` folder would exist in git and be missing from the running server that has to read it. The catalog repo can still pin the folder by sha from this repo.

**The checker.** Schema files are keyed by their path relative to the set root and a `$ref` resolves relative to the referring file (`../theme.schema.json` from inside `warez/`; `src/cplugs/sdk/schema_check.py`). **The schema set digest** is `schema_set_digest()` in `src/cplugs/sdk/schema_digest.py`, pinned in `SCHEMA_SET_DIGEST` and by `tests/python/cplugs/test_warez_schema_set.py`; the catalog repo vendors a byte-identical copy and pins the same value. The app has no `jsonschema` dependency. `src/cplugs/sdk/schema_check.py` is a stdlib checker for exactly the keywords these files use and REFUSES a schema that uses another (`SchemaSet.check_keywords`, enforced by `tests/python/cplugs/test_extension_schemas.py`), so a keyword is never silently skipped.

## 2. The sidecar: `carnivore.json`

One fixed name for every kind. It is never counted as "the manifest": the kind is still decided by the native manifest present (`SKILL.md`, `theme.json`, `.claude-plugin/plugin.json`, `loadout.json`, `cplug.json`). The signed release statement stays `carnivore-release-v1` (nine lines); new envelope fields go into the index item, which ignores extra fields by design.

### The shared envelope (L0)

| Field | Rule |
|---|---|
| `kind` | one of `cplug`, `widget`, `theme`, `skill`, `claude-code-plugin`, `mod`, `loadout` |
| `id` | a bare id for a first-party item, `<publisher>/<name>` for a catalog item; each kind tightens it |
| `name` | the display name. The Plugins page shows it beside the id; for a plugin it must equal the catalog string `cplug.<id>.name` (tested) |
| `version` | the catalog `VERSION_RE`: up to four numeric parts and an optional pre-release |
| `min_app_version`, `author` | semver, string |
| `license` | an SPDX id; required for tier `catalog` |
| `tier` | `builtin`, `catalog`, `dev` (section 4) |
| `scope` | `global`, `project` or both; per kind (a plugin is app-wide) |
| `requires` | `[{id, kind, range?}]`, `kind` a contract kind, `core` (a core feature id) or `mcp` (an MCP server a skill expects) |
| `permissions` | `[{name, reason?}]`; `name` is a row of the permission registry (section 3); `reason` (200 characters) is required for tier `catalog` and shown beside the permission on the consent sheet |
| `owns` | lists of everything the item puts on disk or into the app; purge removes all of it |
| `data` | the stores the item keeps (databases, folders, files), so export and inventory find them without a table in core (section 8). Optional in the base, required for a plugin |

### Per kind (L1)

- **`cplug`** (a plugin that runs beside the app; `cplug` is this repository's code name, to a person it is a plugin). Id `^[a-z][a-z0-9]{1,23}$`, scope `["global"]`, `icon`, `default_enabled`, `owns` keys limited to `routes strings styles assets tests migrations style_guide contributions files`, `requires` kinds `cplug` or `core`. The runtime manifest stays `src/cplugs/<id>/cplug.json`; the sidecar carries the envelope and the parser requires the two to agree on `id`, `version`, `author`, `min_app_version`, `tier`, `icon`, `default_enabled`, permission names and reasons, `requires` and `owns` (`sidecar.DISAGREES`). Folding `cplug.json` into the sidecar is a post-1.0 decision.
- **`theme`**. `theme.json` is the native manifest; scope global; `runs_script` only for publisher `nyedis` . Themes keep their two consents (write the files, run theme scripts).
- **`skill`**. `harnesses` (`claude`, `codex`), `min_harness_version`, `requires_tools`; an MCP dependency is a `requires` entry of kind `mcp`.
- **`mod`**. A plugin for Claude Code with hooks `modules` (`hooks_modules`), installed to `~/.claude/mods` . "Mod" never names a Carnivore-side add-on.
- **`loadout`**. `members`: id, exact version, digest (`loadout.json`, `src/core/skills/loadout_manifest.py`). The signature covers the list; each member's own signature covers its bytes.

## 3. Permissions: one registry

`src/cplugs/sdk/permission_registry.py` is the only table. One row: name (or a `prefix:` family), risk (`low`, `medium`, `high`), the tiers that may ask, the catalog key of the consent sentence, and whether a `cplug.json` may declare it today (`declarable`; a reserved row has a risk but the parser refuses it until its feature is wired). The manifest parser, `host/risk.py`, the consent gate, the default-grant rule (`DEFAULT_GRANTED`, `PLATFORM_GRANTED`) and the tests all read it, which ended the drift: the parser had eight names, `risk.py` twenty, and the two disagreed on whether `dev` or `core` may hold `swarm`, `activity.read` and `work`. A tier outside a row's tiers gets NEVER; an unknown name is HIGH for a first-party tier and NEVER for any other (default deny). Adding a permission is one row and one catalog sentence (`tests/python/cplugs/test_permission_registry.py`).

## 4. Tiers

| Tier | Meaning | Today |
|---|---|---|
| `builtin` | first-party, compiled in, removable, off by default unless the manifest says otherwise | every shipped plugin but `tmdevtools` |
| `catalog` | third party, run out of process in the sandbox, signed and AI-reviewed | designed and built (`src/cplugs/runtime/`), not wired: no `Supervisor(` outside it. Opens after 1.0 behind L2  |
| `dev` | sideloaded or shipped for development, hidden and not loaded until developer mode is on (`host/developer_mode.py`) | `tmdevtools` and Widget Lab (`devwidgetlab`, tier `dev` in `cplug.json` and its sidecar; `tests/python/cplugs/test_dev_tier.py`). The `dev` in the id `devwidgetlab` is the old name prefix; the id cannot change without moving every derived name, so renaming it is a separate migration |

**What happens to `core`.** Core features stop being plugins. No shipped plugin uses `core`. The L0 schema refuses it; `cplug.json` still parses it in 1.0-rc so an old manifest fails with a reason, and it is first-party for `needs_consent` only. It holds none of the first-party-only permissions. It is removed from `MANIFEST_TIERS` at 1.0.

## 6. Lifecycle and zero residue

## 6b. Settings: where a plugin's settings surface

A plugin's `settings_schema` fields (and its extra settings block, such as save's vault panel) surface in the app's Settings screen under the `plugins` heading, at the bottom of its category list. Only an ENABLED plugin that has settings gets an entry; a plugin turned off drops out at once (the list follows the `cplugs` push topic), and with none the heading is hidden. An entry draws the same form as the plugin's pane on the Plugins page and writes through `PUT /api/v1/cplugs/{id}`; its link is `#settings/plugin/<id>`.

The Settings search matches an enabled plugin's settings by each field's `labelKey` and `hintKey` as translated, an optional `keywordsKey` (a catalog string of synonyms, the plugin-side twin of a core row's keywords, accepted by `src/core/item_settings_schema.py` and `opscenter/widgets/validate.ts`), and the plugin's display name. A hit opens that plugin's entry and focuses the field. A plugin writes no Settings code of its own.

## 8. Data: what an item keeps (`data`)

```json
"data": [
  {"id": "boards", "kind": "folder", "root_setting": "boardsRoot", "scope_by": "task_item_id",
   "policy": {"own": "carried", "share": "excluded", "reason": "..."}},
  {"id": "journal", "kind": "db", "path": "mcpondemand.db", "scope_by": "install",
   "policy": {"own": "excluded", "share": "excluded", "reason": "..."}, "secret_columns": []}
]
```

| Key | Rule |
|---|---|
| `id` | required, `^[a-z][a-z0-9_]*$`, unique within the plugin (the parser checks that); the full id is `<plugin>.<id>` |
| `kind` | required: `db`, `folder` or `file` |
| `default` | optional, only with `root_setting`: where the store lives, relative to `<state>/`, while the setting is blank (crate's bundles: `crates`) |
| `sub` | optional, a relative path under the `root_setting` root; not allowed with `path` |
| `scope_by` | required: `session_uuid`, `task_item_id`, `project` or `install` (no subject) |
| `policy` | required: `own` and `share` are each `carried`, `derived` or `excluded`; `reason` is a required non-empty sentence; `purge` is `removed` or `kept` and is REQUIRED on a `root_setting` or `state_path` entry (a store inside the plugin folder is removed with it, so `kept` is refused on a `path` entry); `backup` is `vault` or `none` (the default): `vault` asks the save plugin to back the folder up into its vault, allowed only on a kind `folder` entry that is not a `backup_destination` (below) |
| `role` | optional: `store` (the default) or `backup_destination`, a folder (kind `folder`, placed by a `root_setting` or `state_path`) that holds copies meant to outlive the original |
| `provides` | optional: `backup_points`, on a kind `folder` entry that is where the plugin keeps the backup points of conversations (save's `vault`). At most one entry per plugin. See "Provided roles" below |
| `secret_columns` | optional list of column names, allowed only when `kind` is `db` |

Nothing else is allowed on an entry.

**Not stores.** A lock file, a cache or a scratch folder inside a declared root or the plugin folder is not a store the plugin keeps. If it sits in a declared root (or a plugin folder the plugin lists at all) it is declared `excluded` with a reason saying so (reviewboard's `locks`); one that sits in no declared place needs no entry. For a plugin `data` is REQUIRED and `[]` means "keeps no data"; a missing key follows section 5 (a `cplug_sidecar_invalid` warning in 1.0-rc, a refusal after 1.0). State.json keys are not stores (they belong to the host); a plugin's own db, folder or file is. A folder the plugin only reads (the MCP on demand skills folder) is not a store it keeps.

**Who reads it.** `src/cplugs/sdk/data_decl.py` is the one parser. `load_manifest` attaches the checked block to `Manifest.data`: a tuple of `DataDecl` (`()` keeps nothing; `None` is undeclared, which a structured `cplug_data_invalid` or the sidecar audit reports). Consumers read `Manifest.data`, never the raw file. `tests/python/cplugs/test_plugin_data_block.py` proves every shape rule, the parser, and that every plugin store named in `core/inventory/registry_side.py` has a declaration; the crate and the inventory read the block through `src/core/inventory/plugin_stores.py` ; stores no plugin owns stay in core's tables (the Task Manager's leftovers, `ai_summaries.db`).

## 9. Widgets: the `widget` kind and Widget Lab as the gate

### The record (`widget.schema.json`, L1)

| Key | Rule |
|---|---|
| `id` | `<plugin>.<name>` (`core.notes`, `acme.clock`) |
| `source` | required: `builtin` (compiled into the app), `catalog` or `sideload`. Must agree with `tier`: `builtin`/`builtin`, `catalog`/`catalog`, `dev`/`sideload` |
| `instancing`, `sizes`, `any_size`, `max_per_surface` | the capability contract of `docs/widget-spec.md` sections 1 and 10: `singleton` or `per-target`, the named sizes it calls out, whether it fills any box, the most copies per page |
| `hosts` | required: `home` (the dashboard grid), `terminal` (the terminal canvas and its side and bottom rails), `drawer` (the sidebar widget area), `popout` (the home host in its own window), `glance` (the drawer's mini row; needs `glance.height`, 24 to 160 px). The names are the harness's (`web/src/widget-harness/catalog.ts::HARNESS_ZONES`) |
| `reads` | required: `{kind: route, ref: "GET /path"}` (under `/api/v1`, the fixture's own key form, ids generalized to `{id}`) or `{kind: feed, ref: <push topic>}`. A declarative widget must list at least one, because it has no code to fetch anything else |
| `fixtures` | required: the scenarios it ships, from `data`, `empty`, `stress`. A widget that is not builtin must ship `data` and `empty`; for any widget the gate demands both |
| `fixture` | the harness key the gate draws (the widget's id; an analytics preset is `core.analytics:<preset>`) |

Cross-field rules a schema cannot say (a `glance` host needs a `glance` height, `popout` needs `home`, a singleton holds at most one copy) are in `src/cplugs/sdk/widget_decl.py`.

**Third-party widgets.** The shape is frozen here; the doors open after 1.0 behind L2 . A code-running third-party widget has no representation in 1.0: the only non-builtin form is declarative, and the declarative body (how the app draws one from data) is the post-1.0 design. Nothing in this repo installs one.

### The gate

`venv/bin/python3 -m scripts.widgets.gate [--only core.notes ...] [--themes a,b] [--sizes named|all]` (`scripts/widgets/gate.py`). For each record it draws the `data` and `empty` fixtures through the Widget Lab harness (the page `scripts/widgets/capture.py` and the plugin use) in every declared host, at every size the record calls out (the drawer at its own widths `s`, `m`, `l`, and the glance row when declared), under at least two themes (all capture themes by default), runs the fit check and the junk-text scan on each draw, and writes `build/widget-gate/<id>.gate.json`. A widget fails on any finding, a draw error, a declared size or host the harness does not publish, or a missing fixture. Exit 0 pass, 1 a failure, 2 cannot determine (never a pass). `--sizes all` runs the full standard matrix of `docs/widget-spec.md` section 6.

**The gate record** (`src/cplugs/sdk/widget_gate.py`, schema 1): `{schema, widget, record_sha256, ok, determined, themes, hosts, sizes, fixtures, draws, findings, errors, failures, misses, source_revision, ran_at}`. `record_sha256` is the digest of the contract record it judged, so editing the record makes the gate record stale.

### Widget Lab is tier `dev`

`devwidgetlab` declares `tier: dev` in `cplug.json` and `carnivore.json`. A `dev` plugin reads as off, is absent from `GET /cplugs` and does not start until developer mode is on (`tests/python/cplugs/test_dev_tier.py::test_widget_lab_is_hidden_and_off_until_developer_mode_is_on`).
