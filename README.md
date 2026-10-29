<p align="center">
  <img src="assets/carnivore-wordmark.png" alt="carnivore">
</p>

<h3 align="center">your mac runs the agents. your phone runs the show.</h3>

<p align="center">carnivore keeps claude code and codex running in live tmux sessions on your mac and streams every one to your phone, so the work keeps going whether you're watching or not.</p>

<p align="center">download the desktop app (apple silicon) at <a href="https://carnivore.ai">carnivore.ai</a></p>

---

## what this is

Carnivore is a FastAPI server that owns real tmux sessions on your computer, streams each pane over a WebSocket, and paints it into xterm.js in a browser. The session keeps running whether anyone is watching or not. Open the page from your phone and you are looking at the same live terminal, with the same cursor.

This repository is the open source app, released under the MIT license. The hosted catalog, signing and release infrastructure are not part of it.

## what is in the tree

| path | what it holds |
| --- | --- |
| `src/` | the Python 3.12 server (FastAPI, uvicorn, pydantic) |
| `client/` | the served web client: vanilla JS, CSS, themes, and the built bundle in `client/dist/` |
| `web/` | the Svelte 5, TypeScript and Tailwind sources that build into `client/dist/` |
| `macOS/` | the Electron menu bar app that wraps the server |
| `ios/` | the iOS companion app sources |
| `packages/` | first party plugin packages |
| `scripts/` | build, run, test and maintenance scripts |
| `tests/` | the Python and Node test suites |
| `docs/` | user guide and developer documentation |

## build and run from source

You need macOS or Linux, Python 3.12 or newer, tmux 3.2 or newer, and Node 22 or newer.

```bash
# 1. the server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. the web client bundle (client/dist)
cd web
npm ci
npm run build
cd ..

# 3. run it (binds loopback by default, then open the printed address)
./start.sh
```

`./setup.sh` walks through first time configuration. `config.example.json` and `.env.example` show the available settings. A Docker path is described in `docs/deployment-docker.md`.

## tests

```bash
pip install -r requirements-dev.txt
python3 scripts/run_test_tier.py --smoke        # the fast core set
venv/bin/python3 -m pytest -q tests/<file>.py     # one file
cd web && npm test                                # web client unit tests
```

## documentation

Start with `docs/user-guide/README.md` for using the app. `docs/extension-contract.md` covers writing plugins, `docs/api-keys.md` scripting against the API, and `docs/deployment-docker.md` running it in a container.

## security model

The server binds loopback unless you choose otherwise, every route is authenticated, secrets never ride on a command line, and the content security policy allows no third party origin. See `docs/secret-scanning.md` and `docs/api-keys.md` for details. Report a vulnerability privately to the maintainers through the contact on [carnivore.ai](https://carnivore.ai) rather than in a public issue.

## contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md).

## license

MIT. Copyright (c) 2025-2026 Nyedis Inc. See [LICENSE](LICENSE).
