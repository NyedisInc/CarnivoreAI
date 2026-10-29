# Secret scanning

A pre-commit hook that refuses a commit staging credential material, and
an audit mode for checking the tree as it stands.


## Install and uninstall

```sh
./scripts/install-secret-hook.sh      # writes .git/hooks/pre-commit
./scripts/uninstall-secret-hook.sh    # removes it
```

`.git/hooks` is not version controlled, so a hook committed to the
repository does nothing until it is copied into place. The installer is
the distribution mechanism, and it has to be run once per clone.

The installer prints the exact path it writes. It refuses to overwrite a
`pre-commit` hook it did not write; `--force` backs that hook up first,
and the uninstaller restores the backup. The uninstaller likewise refuses
to delete a hook it does not recognize.

To bypass the hook for one commit:

```sh
git commit --no-verify
```

That is documented deliberately. A hook nobody can get past in an
emergency is a hook that gets deleted instead of bypassed, and then there
is no scanner at all. If you bypass it because it was wrong, say so, so
the detector can be fixed rather than routed around.

## What the hook scans

Only the lines the commit **adds**, read from `git diff --cached -U0`.

A credential already sitting in a file you happened to touch does not
block you. That is a deliberate limit, not an oversight: blocking on
somebody else's old line is the fastest way to get a hook uninstalled,
and the audit mode below is the tool for pre-existing content.

## Second gate: gitleaks

The hook runs a second scanner after the python one passes:

```sh
gitleaks git --staged <repo> --config .gitleaks.toml --redact --no-banner
```

A missing `gitleaks` binary or a missing `.gitleaks.toml` does not
refuse the commit. Both print a NOTE that the second gate did not run
and exit 0, because a hook nobody can get past gets uninstalled and
then both gates are gone. That NOTE means exactly what it says, not
"clean": the python scanner passed, gitleaks did not run, and CI still
runs gitleaks against the same config and can still reject the commit.

## Audit mode

```sh
./venv/bin/python3 scripts/scan_secrets.py                  # whole repo
./venv/bin/python3 scripts/scan_secrets.py src client       # given paths
./venv/bin/python3 scripts/scan_secrets.py --json           # machine output
./venv/bin/python3 scripts/scan_secrets.py --no-excerpt     # position only
./venv/bin/python3 scripts/scan_secrets.py --all-detectors  # noisy, see below
./venv/bin/python3 scripts/scan_secrets.py --no-pragma      # ignore opt-outs
```

History is **not** scanned, by default or otherwise. This repository has
over 600 commits and a history scan is a different job with a different
cost; the tooling here deliberately does not pretend to do it.

## Exit codes are three-valued

| code | meaning |
|---|---|
| 0 | scanned, found nothing |
| 1 | scanned, found credential material (commit refused) |
| 2 | **could not scan** (commit refused, and it says so) |

2 is not 0. A scanner that returns success because it never ran is the
exact false green this project's monitoring has spent months removing.
The hook exits 2 when git fails, when the scanner file is missing, or
when there is no `python3` - and refuses the commit in every case.

## The detectors

`src/core/message_model_secrets.py` is the single source of truth for
what counts as a secret. It is shared with the transcript message model,
so a pattern added for the hook improves that too. Do not write a second
set of patterns anywhere.

Vendor-marker detectors, run by default on files:

| detector | what it keys off |
|---|---|
| `op_service_account_token` | `ops_` plus a long base64 payload |
| `github_token` | `ghp_` `gho_` `ghu_` `ghs_` `ghr_` plus 36+ base62 |
| `aws_access_key_id` | `AKIA` / `ASIA` and the other AWS prefixes plus 16 |
| `aws_secret_access_key` | 40 base64 chars beside a name saying AWS |
| `google_api_key` | `AIza` plus 35 url-safe base64 |
| `slack_token` | `xoxb` `xoxa` `xoxp` `xoxr` `xoxs` plus a payload |
| `stripe_key` `huggingface_token` `npm_token` `gitlab_token` `sendgrid_key` `slack_app_token` | vendor prefix plus the issued length and charset (archive and redaction only, not the file scanner) |
| `pem_private_key` | a PRIVATE KEY header followed by real base64 body |
| `cloudflare_api_token` | 37 to 40 chars beside a name saying Cloudflare |
| `minisign_secret_key` | the minisign secret key header followed by a base64 line |
| `anthropic_api_key` | `sk-ant-api03-` / `sk-ant-admin01-` / `sk-ant-oat01-` / `sk-ant-ort01-` plus 32 to 255 url-safe chars |
| `openai_api_key` | `sk-proj-` / `sk-svcacct-` / `sk-admin-` plus 40 to 255 url-safe chars |
| `carnivore_api_key` | `cak_` plus exactly 43 url-safe chars: Carnivore's own script API key (`docs/api-keys.md`) |

Two of these are **contextual** rather than prefix-matched, because the
credential itself carries no marker. An AWS secret access key is 40
characters of base64 and nothing else; a Cloudflare API token is 40
characters of `[A-Za-z0-9_-]`. Both shapes collide with git sha
fragments, minified identifiers and ordinary base64, so a bare pattern
for either is unusable on a source tree. They require a name beside them
that says AWS or Cloudflare. That trades recall for a false-positive rate
low enough to survive contact with a real repository, and the trade is
the honest one: a scanner nobody keeps installed detects nothing at all.

The PEM detector matches only the **header** and requires base64 body by
lookahead. The finding therefore carries a hash of the header, never of
key material, so the finding record cannot become a second place a
private key partially lives.

## What is never printed

No matched value, anywhere: not in output, not in an error message, not
in a log, not in the JSON. A finding carries path, line, column, detector
name, length and a sha256 prefix. The optional excerpt is built by
masking **every** matched span on the line before the line is truncated,
so a line carrying two credentials cannot print one while reporting the
other. `--no-excerpt` drops even that.

`tests/test_secret_detectors.py` and `tests/test_secret_scan_files.py`
assert this, and each absence assertion is paired with a positive control
asserting the detector name and file path **did** appear - otherwise the
test would pass against a scanner that printed nothing at all.

## Secrets never ride on a command line

## Placeholders, references and indirection

The scanner must not fire on the correct way to handle a credential.
Three classes are excluded, in `is_placeholder()`:

- **Environment indirection**: `${CF_API_TOKEN}`, `%VAR%`,
  `os.environ["X"]`, `process.env.X`, `{{template}}`, `<your-token>`.
- **Documentation padding**: a placeholder word (`example`, `your`,
  `changeme`, `redacted`, and the rest of `PLACEHOLDER_MARKERS`), or a
  run of more than four identical characters.

## Adding a detector

Add a row to `_VENDOR_PATTERNS` in `src/core/message_model_secrets.py`,
a name constant, and an entry in `VENDOR_DETECTORS`. Then add a row to
`CASES` in `tests/test_secret_detectors.py` carrying one sample that must
fire and the placeholder, reference and indirection samples that must
not. The parametrised tests pick it up automatically, and
`test_every_declared_detector_has_a_case_or_is_the_generic_one` fails if
you skip that step.

