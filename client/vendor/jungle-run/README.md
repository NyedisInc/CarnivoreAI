# jungle-run

Prebuilt bundle, vendored as-is from Joe (ccsliinc)'s build of 2026-11-02
(`jungle-run-20261102.zip`, the two-stage build: the jungle, then five base
rooms and a final boss). Do not edit these files; replace the folder with a
new build instead. `client/index.html` loads only `jungle-run-loader.js`; it
fetches the hashed game chunk and `sprites/` relative to its own URL, on demand,
and the tools chunk only when that panel is opened.
No network calls, no storage, no remote URLs.
