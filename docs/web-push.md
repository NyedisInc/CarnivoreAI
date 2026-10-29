# Web push (issue #164, plan D15)

The computer pushes straight to the browser vendors' push services (Apple, Google, Mozilla) when the approval
inbox gains an item. Ruled by Alex (example-owner), 2026-09-30: "web push, and the payload is only 'approval needed'".

## What is sent

Two paths share one sender (`src/core/web_push/sender.py`).

- The typed path (issue #1278, reverses the approval-only payload): a push is the destination
  `webpush:<subscription id>` of the notifications engine (`src/core/notifications/kinds/webpush.py`). The
  plaintext is `{"title": ..., "body": ..., "path": ...}`: the fixed per-type copy from the catalog and the
  relative session path from `notifications/links.py` (`/` when the event has no session). Never details, never
  an absolute link, never agent text. `client/sw.js` renders it as plain text and a tap opens `path` only when it
  is a same-origin relative path.
- The old fixed path: `{"title":"carnivore","body":"approval needed"}` (`sender.FIXED_PAYLOAD`), sent by
  `PushSender.notify` for the test button only (`POST /push/test`). The approval-only trigger is RETIRED (#1278
  cutover): the approvals inbox no longer calls the sender, and `PushSender.on_inbox_gain` is deleted.

Ruled by Alex (example-owner), 2026-09-30: "web push, and the payload is only 'approval needed'"; superseded for the
typed path by the #1278 plan ("Web push carries typed fixed copy"). No session name, project or question text
rides in a header or a log.

### Typed path: coalescing, pruning, switches

- Coalescing is per (subscription, type): a second typed push to the same pair inside `COALESCE_SECONDS` (10 s)
  is dropped as already delivered; another type or another subscription is its own key. The push service also
  collapses undelivered repeats by the `Topic` header, a short hash of the type. This replaces the old 60 s floor,
  which stays only on the fixed path.
- A 404 or 410 from the push service deletes the subscription, same as on the fixed path. Any other status is
  stored as `last_result` and classified for the engine (5xx server, 429 rate limited, 401 and 403 auth).
- The per-computer pause switch and a session's mute now cover web push, because the engine decides on
  this path; no inbox listener pushes any more, so nothing bypasses them.
- A new subscription is seeded with the global tick defaults (`seed_destination_ticks`), and ticks are local.

## Trigger and limits

`ApprovalsInbox.on_gain(listener)` fires once per refresh that ADDS an item id (a removal or an unchanged list
does not; a changed fingerprint is a new id). Nothing registers a web push listener on it any more (the old
approval-only trigger was retired in #1278); the approvals source (`notifications/sources/approvals.py`)
emits the event and the engine decides. Remote (`remote:`) sessions are left out of the signature, like the owner's list. At most one push per subscription per 60 s (in memory; `POST /push/test`
skips the wait). Headers: `TTL: 3600`, `Urgency: high`, `Topic: approval` (repeats collapse at the service).

## Wire format (`src/core/web_push/`)

- `vapid.py`: RFC 8292. A P-256 key created once at `<state_dir>/web_push_vapid.pem`, mode 0600. ES256 JWT with
  `aud` = the endpoint's origin, `exp` <= 12 h, `sub` from `config.json` `web_push.subject` (a `mailto:` or https
  URL; default `https://carnivore.ai`). Header `Authorization: vapid t=<jwt>, k=<public key>`.
- `encrypt.py`: RFC 8291 over RFC 8188 aes128gcm, one record, `cryptography` only. Proven against the RFC 8291
  section 5 vector (`tests/python/web_push/test_web_push.py`).
- `endpoints.py`: the allow-list. Only https on `web.push.apple.com`, `*.push.apple.com`, `fcm.googleapis.com`,
  `updates.push.services.mozilla.com`, no explicit port, no credentials. Checked when a subscription is added AND again at
  send time (a stored row that fails is deleted), and redirects are not followed. This is what stops the computer
  being used as an SSRF cannon. Edge's Windows service (`*.notify.windows.com`) is not on the list.
- `store.py`: subscriptions in `<state_dir>/web_push_subscriptions.json`, mode 0600 (it holds each auth secret).
  A row: `id, endpoint, p256dh, auth, device_id, created_at, last_result {status, at}`. The endpoint is the identity.
  404 and 410 from the service delete the row; any other answer is stored as `last_result` (status 0 = no answer).
  `SubscriptionStore.remove_for_device(device_id)` runs when a paired device is revoked (`DELETE /phone-link/devices/{id}`).
  A client cannot set `device_id`: `POST /push/subscriptions` records the device the link gate verified from the
  `__Host-cc_link` cookie (`scope["link_device"]`, only when the request came through the link); a subscription made on the computer
  has none. The last push result per device shows in settings > mobile sync.
  After the insert the route re-checks that the device is still paired; if a revoke ran meanwhile it removes the
  subscription and answers 403, and the revoke route removes a device's subscriptions even when the device is already
  gone (404), so a retry can finish the cleanup. Subscriptions created over the link BEFORE device binding shipped carry
  no device, so a revoke will not remove them: remove them by hand in settings. None exist on the live computer yet.
- Logs carry the service host and error type only, never an endpoint, key or secret.

## Routes (`src/api/web_push_routes.py`, owner auth)

`GET /push/vapid-public-key`, `POST /push/subscriptions` (endpoint host and key lengths validated, 422 on
refusal, 409 past 20), `GET /push/subscriptions` (public view: id, service host, device_id (server-set only), created_at,
last_result; never an endpoint or key), `DELETE /push/subscriptions/{id}`, `POST /push/test` (429 inside a 5 s cooldown).

A paired computer's peer token is a different credential from an owner access token: `require_auth` refuses it with 401, which
`tests/python/federation/test_federation_route_inventory.py` proves for every route not on its peer allow-list (these are not).

## Client

`client/sw.js`, served at `/sw.js` (`src/main.py`, `Cache-Control: no-cache, must-revalidate`, listed in
`PUBLIC_HTTP` because a browser fetches a worker without a bearer token). Push and notificationclick handlers
only: no fetch handler, no caching. The CSP's `default-src 'self'` covers a same-origin worker. Settings,
notifications, "alerts on this device" (`WebPushPanel.svelte`): "alerts on" appears only when the page is an
installed app (display-mode standalone) and `PushManager` exists; it asks permission, registers the worker,
subscribes with the VAPID key and posts the subscription. iOS delivers web push only to a home-screen app.
