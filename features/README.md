# Feature catalog

A per-change, machine-readable record of what this product does and what
changed, release by release. Both humans and agents work this repo in
parallel, so the format is fragment files: every PR adds its own small JSON
files here and never edits a file another PR might also be touching. The
one shared output, `FEATURES.md` (plus `features/index.json` and
`features/schema.json`), is generated from these fragments once, at merge
time on master, by `scripts/dist-at-merge.sh`. **Never hand-edit `FEATURES.md`,
`features/index.json` or `features/schema.json`, and never commit them on a
branch** - `scripts/web-build-check.sh --branch` refuses one that does.

This is a per-change feature log, not release notes. The GitHub release
body stays the record of what shipped in a given release; see
`docs/DECISIONS.md` for that distinction and `docs/integration-1.4.0-history.md`
for why a second release-notes file is rejected.

## What's in here

```
features/
  areas.json                 ordered list of areas (site nav): id, name, blurb
  catalog/<feature-id>.json  one file per feature, its CURRENT state
  changes/<date>-<pr>-<slug>.json  one immutable file per PR (the update log)
  media/<feature-id>/*.png|gif|svg|webp  screenshots, icon states, GIFs (#846)
  capture/<feature-id>.json  the steps that regenerate that feature's media
  schema.json                GENERATED: draft 2020-12 JSON Schema, do not edit
  index.json                 GENERATED: areas + catalog + changes in one fetch
README.md                    this file
```

## Every product-changing PR

Adds exactly one file under `features/changes/`, and creates or edits
whichever `features/catalog/*.json` files it affects. This includes fixes.
A pure refactor with no user-visible effect still logs an entry, with
`type: "internal"` - those are hidden from the catalog's own visible update
log but still exist for the record.

The easiest way to add one is the tool itself:

```
python3 scripts/features.py new-change \
  --type fixed \
  --features session-restart \
  --summary "fix the restart picker losing the arm checkbox on reopen" \
  --issue 900 --pr 903
```

This writes `features/changes/<today>-903-fix-the-restart-picker-losing-....json`.
Use `--type internal` and omit `--features` (or pass `--features ""`) for a
refactor with no user-visible change. `--pr` is required: the PR number is
already known at claim time, because claiming an issue opens a draft PR
(see `.claude/skills/work/SKILL.md`).

## Catalog entry fields (`features/catalog/<id>.json`)

The filename (minus `.json`) IS the id, kebab-case.

| field | required | notes |
|---|---|---|
| `id` | yes | must equal the filename |
| `name` | yes | |
| `summary` | yes | one user-facing sentence |
| `description` | no | markdown |
| `area` | yes | must be listed in `features/areas.json` |
| `status` | yes | `stable`, `beta`, `deprecated` or `removed` (a removed feature keeps its file) |
| `since` | yes | `YYYY-MM-DD` |
| `updated` | yes | `YYYY-MM-DD`; must change whenever the file changes on a day other than today. `check --branch` compares it to the merge base and only fails when it is BOTH unchanged AND not today - a same-day second edit can leave today's date as it is |
| `surfaces` | no | where it shows up in the UI |
| `api_routes` | no | ties to the "everything is API'd" rule; a future MCP server can be generated from this |
| `docs` | no | repo-relative doc paths |
| `issues` | no | issue numbers |
| `keywords` | no | |
| `where` | no* | list of plain steps: how to find it in the UI |
| `how_to` | no* | ordered steps to use it |
| `examples` | no* | short scenarios: why and when you would use it |
| `media` | no* | list of `{kind, file, caption, alt, theme?, state?}`, see "Showing a feature" |
| `media_exempt` | no | a reason there is nothing to see (API-only, background); replaces `media` |

\* Optional in the schema, REQUIRED by `check --branch` for any feature an
`added` or `changed` change entry names (see "Showing a feature").

## Change entry fields (`features/changes/<date>-<pr>-<slug>.json`)

Immutable once merged - never edit one after it lands.

| field | required | notes |
|---|---|---|
| `date` | yes | `YYYY-MM-DD` |
| `type` | yes | `added`, `changed`, `fixed`, `removed`, `deprecated`, `security` (Keep a Changelog's vocabulary), or `internal` |
| `features` | yes | catalog ids this touches; each must exist; empty only when `type` is `internal` |
| `summary` | yes | one user-facing line |
| `details` | no | markdown |
| `issue` | no | |
| `pr` | no | the PR number |
| `breaking` | no | boolean |
| `media_unchanged` | no | `true`: this change touched the feature's `surfaces` without changing how it looks, so no recapture |

## Showing a feature (issue #846)

### `media`

```json
"media": [
  {"kind": "screenshot", "file": "drawer.png", "caption": "an asleep session in the drawer",
   "alt": "the agents drawer with one row showing a moon light"},
  {"kind": "icon", "file": "moon.png", "state": "asleep", "caption": "the asleep light",
   "alt": "a small moon-shaped status light"},
  {"kind": "gif", "file": "sleep-wake.gif", "caption": "sleep, then wake",
   "alt": "the row menu's sleep action turning a light into a moon and back"}
]
```

- `kind`: `screenshot` (png or webp), `gif`, or `icon` (png, svg or webp).
  `state` names an icon's variant or mode (on/off, asleep/awake); `theme`
  names the theme it was captured under when not the default.
- `file` is a plain name inside `features/media/<feature-id>/` - no `/`, no
  `..` - and must exist. `alt` is required and non-blank.
- Every png/gif/webp must be produced by a shot in that feature's capture
  spec, so it can be regenerated; an svg icon may be copied in by hand. A
  file in the folder that no entry lists fails `check` (delete it or list it).

### Capture specs: `features/capture/<feature-id>.json`

```json
{
  "feature": "session-sleep",
  "viewport": {"width": 1440, "height": 900},
  "seed": {"sessions": [{"name": "api-server", "agent": "claude"},
                        {"name": "web-client", "agent": "claude", "asleep": true}]},
  "shots": [
    {"name": "drawer", "kind": "screenshot", "steps": [{"goto": "/"}], "target": "#session-sidebar-list"},
    {"name": "sleep-wake", "kind": "gif", "steps": [{"goto": "/"}],
     "record": [{"click": "..."}, {"wait": 1500}], "target": "#session-sidebar-list"}
  ]
}
```

- Steps are one-key objects: `goto` (a path), `click`, `dblclick`, `hover`,
  `wait_for` (selectors), `press` (a key), `type` (text), `wait` (ms),
  `set_theme` (a theme id, set as the global theme), `set_viewport`
  (`{width, height}`), `drag` (`{from, to}` selectors), `scroll`
  (`{selector, y}`), `api` (`{method, path, body}` against `/api/...`).
  Strings may use `{session.<name>.id}`, `{session.<name>.tmux}`,
  `{session.<name>.row}` (the sessions row id a Layout shape keys on) and
  `{session.<name>.uuid}` for seeded sessions.
- A shot: `name` (the file stem), `kind`, `steps` run first, optional
  `target` (a selector: the shot is that element plus `pad` pixels; the
  whole viewport otherwise) or a fixed `clip` (`{x, y, width, height}`,
  for a region that spans a popup and its anchor), `hide` (extra selectors hidden for
  determinism). A `gif` also takes `record`: the steps whose recording
  becomes the GIF (the setup `steps` are trimmed off).
- `seed.sessions`: throwaway sessions in neutral `/tmp/carnivore-demo/`
  folders, each registered as a project (`project_row: false` skips that). `agent: shell` (default) is a zsh with a neutral prompt;
  `claude`/`codex` run a demo launch wrapper of that family that starts no
  real agent and needs no credential; `asleep: true` sleeps a claude one.
  `timers: [{kind: wakeup, delay: 1080}, {kind: cron, cron: "*/15 * * * *"}]` on a
  claude one appends live timer calls and a pid registry record for its pane
  (`scripts/feature_capture_timers.py`, issue #893).
  `seed.preferences` sets `ui_preferences` values; top-level `theme` sets
  the global theme (default: the app default).
- `viewport` defaults to 1440x900; `scale` sets the device pixel ratio.
  `drawer_width` (240-480) stores the drawer width before the page loads: at the 320px
  default a row is 293px and a container query hides the cozy subagent and timer chips at 300px or less.

### Running it

```
python3 scripts/feature_capture.py <id> [<id> ...]
python3 scripts/feature_capture.py --changed   # specs or surfaces changed on this branch
python3 scripts/feature_capture.py --all
```

It waits (bounded, 10 minutes) while the 1-minute load average is over 10,
leases a `scripts/testsrv` slot (never :8000, never the live `cloude`
socket), points it at your checkout, resets it before every feature, runs
the shots in headless Chromium at a fixed viewport, squeezes PNGs through
`pngquant`, turns a GIF's recorded webm into a GIF with `ffmpeg`
(palettegen + paletteuse, at most 12 fps and 800 px wide, trimmed to the
recorded steps), writes only `features/media/<id>/`, then resets and
releases the slot. Look at what it wrote before you commit it.

### What `check --branch` enforces

- A branch adding or editing an `added`/`changed` change entry: every
  feature it names needs non-empty `where`, `how_to`, `examples` and at
  least one `media` item, or `media_exempt`.
- If the diff also touches one of that feature's path-shaped `surfaces`,
  something under `features/media/<id>/` must have changed on the branch,
  or the change entry says `"media_unchanged": true`.
- `fixed`, `security`, `removed`, `deprecated` and `internal` entries never
  require any of this.

Every failure names the exact fix: `python3 scripts/feature_capture.py <id>`.

## Release grouping is derived, never typed in

`scripts/features.py render` finds the commit that added each change file,
then the first `v*` tag that contains it. No tag contains it yet: the
change is listed under `Unreleased`. Cutting a release needs no extra step
here.

**Backfilling an entry for a commit that already shipped needs the explicit
`release` field.** Derivation keys off the commit that added the JSON
FRAGMENT FILE, never off the original product commit it documents. A
fragment written today for a commit that shipped in, say, v1.12.13 was
itself added today, long after v1.12.19 - so without an override it falls
into `Unreleased` (or whatever release is currently pending), not the
release it actually describes. Set `"release": "v1.12.13"` in the fragment
to pin it; `group_by_release` honors it outright and skips derivation for
that entry. Leave the field out for every ordinary, same-day entry - that
is still 100% of entries in practice.

**A preview build never creates a release group.** `~/bin/carnivore-preview`
(`docs/preview-install.md`) stamps a pre-release version such as
`1.12.20-preview.30.g059b3f0` only into its build worktree's UNCOMMITTED
`macOS/package.json`, and creates no tag, so neither the `v*` tag list nor
the pending-bump rule (`_pending_release_tag`, which reads the committed
`macOS/package.json`) ever sees it; its changes stay under `Unreleased` until
the real release is tagged. Never tag a preview: `_version_key` pulls every
digit out of a tag, so a `v1.12.20-preview...` tag WOULD become a group.

## Auditing a release for a missing entry

```
python3 scripts/release/changelog_audit.py --range v1.12.18..v1.12.19
python3 scripts/release/changelog_audit.py --range v1.12.19..HEAD --verbose
```

It is a heuristic screen, not a semantic one - full limitations are in the
script's own module docstring. The two that matter most: the tweak/product
line is drawn on file extension and diff size, not on judgment about user
impact, and it cannot match a commit to an entry added by a LATER commit in
the same PR (exact-sha matching only) - a human still has to look at what
it prints and clear the ones already covered. It is proposed, not yet
required, as a step in the pre-version-bump pipeline; see
`.claude/skills/work/SKILL.md`.

## Validating

```
python3 scripts/features.py check           # every JSON file is well formed
python3 scripts/features.py check --branch  # also: does this PR need a change entry
python3 scripts/features.py render          # regenerate FEATURES.md, index.json, schema.json
```

`check` also validates media and capture specs (above). `check --branch` runs automatically before a merge
(`.claude/skills/work/SKILL.md`, "Merging") and fails closed: if the diff
touches product code (`src/`, `web/src/`, `client/` except `client/dist/`,
`macOS/`) with no new `features/changes/*.json` file, it exits 1 and prints
the exact `new-change` command to run.
