# vendored xterm.js bundle

`xterm.css`, `xterm.js`, `xterm-addon-fit.js`, `xterm-addon-webgl.js`,
`xterm-addon-unicode11.js`, `xterm-addon-search.js` and `xterm-addon-web-links.js`
(`@xterm/addon-web-links` 0.11.0, #2725; MIT, notice in `macOS/payload/notices/vendored.json`)
are unmodified files
pulled straight from jsDelivr at the pinned versions below and committed
as-is. There is no
build step here - unlike `client/vendor/codemirror/`, these ship from
their npm packages as plain browser files, so there is nothing to bundle.

## why vendored instead of CDN-loaded

`client/index.html` previously loaded the first five of these from
`cdn.jsdelivr.net`. On desktop that CDN is fast and typically warm-cached,
so the failure mode below never surfaces there. On the user's phone
(Brave), Shields blocks or delays third-party requests by default,
including CDN-hosted JS and CSS. When `xterm.css` is missing or arrives
late, xterm's internal character-measurement element - the hidden DOM node
it uses to compute cell width/height - never gets the right metrics.
Backend pane dimensions still come out correct (they are computed
independently), so the terminal LOOKS fine from the server's point of view
while the on-device render is garbled. Serving these files from this
app's own origin removes third-party-CDN reachability from the picture
entirely: no CDN request, no Shields interaction, no race between script
load and stylesheet load. Same reasoning that put CodeMirror under
`client/vendor/`, see that directory's `VERSION.md`.

## pinned versions (moved from the deprecated `xterm` packages to `@xterm/*` on 2026-11-12, DEP-11)

The files keep their old names (`xterm-addon-*.js`) because the page, the relay viewer, the pop-out and the packaged app's
notices load them by name; only the source packages changed. The old `xterm@5.3.0` family is deprecated on npm ("Move to
@xterm/xterm instead") and gets no fixes. The UMD globals (`Terminal`, `FitAddon.FitAddon`, `WebglAddon.WebglAddon`,
`Unicode11Addon.Unicode11Addon`, `SearchAddon.SearchAddon`, `WebLinksAddon.WebLinksAddon`) are unchanged.

| file | package | version | source URL |
|---|---|---|---|
| xterm.css | @xterm/xterm | 5.5.0 | https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css |
| xterm.js | @xterm/xterm | 5.5.0 | https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.js |
| xterm-addon-fit.js | @xterm/addon-fit | 0.10.0 | https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.js |
| xterm-addon-webgl.js | @xterm/addon-webgl | 0.18.0 | https://cdn.jsdelivr.net/npm/@xterm/addon-webgl@0.18.0/lib/addon-webgl.js |
| xterm-addon-unicode11.js | @xterm/addon-unicode11 | 0.8.0 | https://cdn.jsdelivr.net/npm/@xterm/addon-unicode11@0.8.0/lib/addon-unicode11.js |
| xterm-addon-search.js | @xterm/addon-search | 0.15.0 | https://cdn.jsdelivr.net/npm/@xterm/addon-search@0.15.0/lib/addon-search.js |
| xterm-addon-web-links.js | @xterm/addon-web-links | 0.11.0 | https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.js |

`@xterm/addon-web-links` 0.11.0 was first taken from registry.npmjs.org (Joe (ccsliinc), 2026-11-12, Task Manager "yes"): the
tarball's sha512 matched the registry's `dist.integrity`
`sha512-nIHQ38pQI+a5kXnRaTgwqSHnX7KE6+4SVoceompgHL26unAxdfP6IPqUTSYPQgSwM56hsElfoNrrW5V7BUED/Q==`, its peer dependency is
`@xterm/xterm@^5.0.0` (accepts 5.5.0), and `lib/addon-web-links.js` is the file vendored here. `fetch.sh` re-fetches the same
file from jsDelivr and pins its sha256.

## sha256

```
ba8e6985669488981ccf40c0cefe3aba80722cb6c92de7ad628b0bd717faf2b6  xterm.css
1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495  xterm.js
bdaefa370b1bfc42ee88d46fe6072400902a4d4b2d45cd93438dda9b23c97089  xterm-addon-fit.js
9ffa9ac3ff6d47d4e6216ed1972ca8e0b5336cef744f50ebdc3f67b0ed727cdb  xterm-addon-webgl.js
b0c3be540a9984713aea996966c24ed1a639d11f60d44986b22661e3a8a148d0  xterm-addon-unicode11.js
3cf52d71d9deb4ba60125087434c53e3fb35bb2249db9b13987991fd2db1c7bd  xterm-addon-search.js
f230a6c8211ce4614dda5441f27b603c7c1ca95151a655bc0efac6377ee643f0  xterm-addon-web-links.js
```

## updating

Dated snapshot, not auto-updated. To bump, edit the version variables and
the matching sha256 in the `ASSETS` list inside
`scripts/xterm-vendor/fetch.sh`, run it with no arguments, and update the
version table and sha256 block above to match what it prints. The script
re-downloads every file and exits non-zero on the first hash that does not
match, so a bump you have not recorded here cannot land quietly.

`@xterm/addon-search` 0.15.0 pairs with `@xterm/xterm` 5.5.0
(its `peerDependencies` name `@xterm/xterm@^5.0.0`). Its UMD bundle defines the
global `SearchAddon`, and the class is `SearchAddon.SearchAddon` - the
same double-name shape the fit and webgl add-ons use.

`client/js/canvas-font-trim.js` (#2806) is a shim loaded before xterm.js: Chromium
156 rejects a canvas `ctx.font` with a leading space and the webgl add-on emits one
for regular text. xterm 6.0.0 / addon-webgl 0.19.0 still emit it as of 2026-11-05.
It installs only when a probe shows the bug; drop it when the probe stops installing.
