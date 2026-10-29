# jungle-run

Prebuilt bundle, vendored as-is from Joe (ccsliinc)'s build of 2026-10-19
(`jungle-run-20261019.zip`). Do not edit these files; replace the folder with a
new build instead. `client/index.html` loads only `jungle-run-loader.js`; it
fetches the hashed chunk and `sprites/` relative to its own URL, on demand.
No network calls, no storage, no remote URLs.
