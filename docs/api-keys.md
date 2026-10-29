# API keys for scripts

## 2. The key

- **Shape.** `cak_` plus `secrets.token_urlsafe(32)` (256 random bits, 43 url-safe characters). The prefix lets the secret
  scanner find one (`carnivore_api_key` in `src/core/message_model_secrets.py`, `docs/secret-scanning.md`) and lets
  `require_auth` tell a key from a JWT without trying to decode it.
- **Shown once.** The create answer carries the plaintext; nothing else ever returns it, and the server never stores it.
- **Stored hashed.** `api_keys.db` in the state dir (`state_dir()`), mode 0600, opened `O_NOFOLLOW` (a symlink there is
  refused). One table, `api_keys`: `id` (`key_` plus 12 hex), `name`, `key_hash` (sha256 hex of the whole key; plenty for a
  256-bit random token, and compared with `hmac.compare_digest`), `display_prefix` (`cak_` plus the first 6 characters),
  `created_at`, `last_used_at`, `revoked_at` (epoch seconds).
- **Limits.** Names are 1 to 60 characters, no control characters. At most 50 live keys.
- **Code.** `src/core/api_keys/` (`store.py`, `fence.py`, `gate.py`); routes `src/api/api_keys_routes.py`.

## 3. Authentication

`src/api/auth.py::require_auth` is the one dependency every owner REST route uses. When the bearer starts with `cak_` it
calls `api_keys.gate.admit` instead of decoding a JWT:

1. Look the key up by hash, off the event loop. Unknown, malformed or revoked: **401** `{"reason": "api_key_invalid"}`.
   The file is read on every request, so a revoke takes effect on the very next one.
2. Check the fence (section 4). Fenced: **403** `{"reason": "api_key_forbidden"}`.

`last_used_at` is written at most once a minute per key (the throttle reads the stored value). An unreadable key file is
**503** `api_key_store_unavailable`, never a pass. The key is never logged; the key id is (`api_key_created`,
`api_key_revoked`, `api_key_refused`, `api_key_fenced`).

Out of scope, unchanged: WebSockets (`/ws/*` still take only the JWT subprotocol) and `/mcp` (hook and `cmcp_` tokens).

## 4. The fence

One explicit list, `src/core/api_keys/fence.py::FENCED`, matched by path prefix against the routed path and the URL path.
A key is refused on:

| prefix | family | why |
|---|---|---|
| `/api/v1/mcp-admin/tokens` | minting and revoking MCP client tokens | minting a credential, the same class as creating a key |

There is no password route and no authenticated TOTP reset route in this build; TOTP setup lives under `/auth/enrollment`,
which the `/auth/` prefix covers. Most `/auth/*` routes never read a bearer at all (they take a TOTP code or a refresh
token), so a key there mints nothing; the fence keeps any future one that does use `require_auth` from taking a key.

`tests/python/api_keys/test_fence.py` has one test per family (key refused 403, owner JWT accepted) and one that every
listed prefix still matches a real route of the app, so a renamed route cannot silently leave the fence.

## 5. Routes

- `POST /api/v1/api-keys` `{name}` -> 201 `{key: row, secret}`. 422 for a blank name or 50 live keys; 400 from the app's
  validation for a name over 60 characters.
- `GET /api/v1/api-keys` -> `{keys: [row, ...]}`, newest first, revoked ones included. A row is `id`, `name`,
  `display_prefix`, `created_at`, `last_used_at`, `revoked_at`; never the key or its hash.
- `DELETE /api/v1/api-keys/{key_id}` -> `{revoked: row}`; 404 for an unknown id. Revoking twice keeps the first time.

## 6. MCP

## 7. Settings

## 8. Using a key

Make the key in Settings on the computer the script talks to, copy it into a 1Password item at once, and have the script
read it at run time. For the crate CLI: `--token-op op://Vault/<item>/credential` (or `--token-env NAME`). Send it as
`Authorization: Bearer cak_...`. Revoke it when the script is retired or the computer leaves.
