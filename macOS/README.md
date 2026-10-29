# Cloude Code - macOS Menu Bar App

Native macOS menu bar application for managing Cloude Code server.

## Quick Start

```bash
# Install dependencies
npm install

# Run in development mode
npm start

# Build DMG installer
npm run build
```

## Architecture

```
┌─────────────────────────────┐
│  Electron Main Process      │
│  (main.js)                  │
│    ├── Tray Manager         │
│    ├── Menu Builder         │
│    └── Stats Polling (5s)   │
└────────┬────────────────────┘
         │
    ┌────┴────────────────┐
    │                     │
┌───▼──────────┐  ┌──────▼─────────────┐
│ Server       │  │ LaunchAgent        │
│ Manager      │  │ Installer          │
│              │  │                    │
│ • Start      │  │ • Install plist    │
│ • Stop       │  │ • Remove plist     │
│ • Restart    │  │ • Toggle auto-     │
│ • Health     │  │   launch           │
│   Check      │  │                    │
└───┬──────────┘  └────────────────────┘
    │
    │ spawns & controls
    ▼
┌────────────────────────────────┐
│  Python FastAPI Server         │
│  (<serverDir>/venv/bin/python3)│
│                                │
│  API: http://localhost:8000    │
│  • GET /api/v1/health          │
│  • POST /api/v1/shutdown       │
│  • Web UI accessible           │
└────────────────────────────────┘
```

## Files

- **main.js** - Electron main process, tray menu, stats polling
- **server-manager.js** - Python subprocess lifecycle management
- **launchagent-installer.js** - macOS auto-launch setup
- **second-instance.js** - what a second launch means (the app takes a single-instance lock; a second launch brings the first window forward)
- **engine/fs-perms.js** - keeps `<userData>/server` private (mode 0700)
- **package.json** - NPM config with electron-builder setup
- **assets/** - Menu bar icons (22x22, 44x44)

## Menu Structure

```
● Server: Running
Session: my-project
Tunnels: 2
────────────────
Open Terminal
Open in Browser
────────────────
Restart Server
Stop Server
────────────────
Start Engine at Login ✓
Quit Carnivore
Quit and Stop Engine
```

## How It Works

### Server Management

1. **Start**: Spawns `<serverDir>/venv/bin/python3 -m src.main` subprocess,
   with `cwd` set to `<serverDir>` and `CLOUDE_APP_VERSION` injected from
   `app.getVersion()`.

   `<serverDir>` is **NOT** `../` in a packaged app. `bootstrap.js` superseded
   that model: it provisions `<userData>/server/` with its own copy of
   `src/`, `client/`, `requirements.txt`, `requirements.lock`, a `venv`, `.env`, `config.json` and
   a generated `VERSION` stamp, and re-syncs the bundled artifacts into it on
   every packaged launch. Only in dev (`npm start`) does `serverDir` resolve
   to the repo root one level up. Anything that assumes a sibling `../venv`
   is describing the dev tree, not the shipped app.

   `<userData>` is `~/Library/Application Support/Carnivore Menubar/` as of
   the Carnivore rename's Phase 9 bundle-id cutover (`userdata-migration.js`,
   `main.js` at the top of `app.whenReady()`). The first launch after
   upgrading a pre-Phase-9 install renames the old
   `~/Library/Application Support/cloude-code-menubar/` directory into that
   new location in place - same volume, one atomic move, nothing copied -
   before anything else in the app reads `app.getPath('userData')`.
2. **Monitor**: Polls `GET /api/v1/health` every 5 seconds
3. **Restart**: Calls `POST /api/v1/shutdown`, waits 2s, then starts
4. **Stop**: Sends shutdown API call + SIGTERM signal

### Stats Polling

```javascript
setInterval(async () => {
  const stats = await fetch('http://localhost:8000/api/v1/health');
  // Update menu with: status, session_name, tunnel_count
}, 5000);
```

### Auto-Launch

Creates `~/Library/LaunchAgents/ai.carnivore.menubar.plist`:

```xml
<plist>
  <dict>
    <key>Label</key>
    <string>ai.carnivore.menubar</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Applications/Carnivore.app/Contents/MacOS/Carnivore</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>/Users/YOU/Library/Logs/Carnivore/menubar.log</string>
    <key>StandardErrorPath</key><string>/Users/YOU/Library/Logs/Carnivore/menubar-error.log</string>
  </dict>
</plist>
```

An install upgrading from a pre-Phase-9 build carries its login (`Start Engine at Login`)
state forward automatically: `launchagent-installer.js`'s
`migrateLegacyIfNeeded()` reads whether the OLD
`com.cloudecode.menubar.plist` was loaded, unloads it, writes and loads this
new plist in its place with the same enabled state, and only then deletes
the old plist file - so a failure partway through leaves the old login item
working rather than leaving neither installed.

## Building

```bash
npm run build
```

`npm run build` and `npm run package` are development builds: signed ad hoc,
not notarized, no keychain read. A release is `scripts/release-build.sh`: it
signs with the Nyedis (ARD6KN4BX4) Developer ID identity from the
dedicated signing keychain, notarizes and staples, and falls back to ad hoc
when that identity is not present. See `docs/code-signing.md`, "Release signing
and notarization". When the signing keychain is present and `package.json` has
`"requireSpareIndexKey": true` (set by the 1.0 release checklist, #1947), it
refuses to build while the catalog's spare index key is still the placeholder
(`scripts/release/spare_key_gate.py`, `docs/catalog.md`, "What Alex needs to do");
otherwise it warns loudly, and an ad hoc build only warns.

Creates:
- `dist/Carnivore.dmg` - macOS installer
- `dist/mac/Carnivore.app` - App bundle

### The dependency lock and the cloudflared pin (R1-16)

First run installs `requirements.lock` (repo root) with `--require-hashes --only-binary :all: --no-deps`; nothing unhashed
runs. After any change to `requirements.txt`, regenerate it and restore the header comment:

```bash
uv pip compile requirements.txt --generate-hashes --universal --python-version 3.12 --only-binary :all: --no-header -o requirements.lock
python3 scripts/release/requirements_lock.py        # exit 0 when every pin has a hash and covers requirements.txt
```

Check a new lock resolves for 3.12, 3.13 and 3.14 on both arches with `pip install --dry-run --require-hashes
--only-binary :all: --no-deps --platform macosx_14_0_x86_64 --target <scratch> -r requirements.lock` from a throwaway venv of
each Python (and natively for arm64). Bootstrap refuses a Python newer than 3.14 until that proof is extended
(`MAX_PROVEN_MINOR` in `python-lock.js`).

To bump cloudflared, download both darwin archives of the new release yourself, run `shasum -a 256` on each tgz and on
the extracted binary, and change `VERSION` and the four hashes in `cloudflared-pin.js` together. `scripts/release-build.sh`
writes the pip-audit result to `dist/pip-audit.txt` (record only).

## Distribution

The build bundles:
- Electron runtime
- All JavaScript files
- Python venv, src/, client/ from parent directory
- .env, config.json

**Bundle size**: ~200-300MB (includes entire Python venv)

### Optimization (Future)

Use PyInstaller to create standalone Python binary:

```bash
cd ..
pyinstaller --onefile --add-data "src:src" --add-data "client:client" src/main.py
# Then bundle dist/main instead of venv/ (~50MB vs ~300MB)
```

## Development

### Running Locally

```bash
npm start
```

**Note**: Electron app will appear in menu bar, not Dock. Look for icon in top-right.

### Debugging

Server logs appear in Electron console:
- stdout: `[SERVER] ...`
- stderr: `[SERVER ERROR] ...`

View with: `npm start` (logs to terminal)

### Testing Without GUI

```bash
# Syntax check
node -c main.js

# Test server manager module
node -e "const SM = require('./server-manager'); const sm = new SM(); console.log('OK')"
```

## Icon Guidelines

See `assets/README.md` for:
- Design requirements
- Size specifications
- Generation scripts
- .icns conversion

## Troubleshooting

### App doesn't appear in menu bar

- Check Electron version compatibility
- Try: System Preferences → Security → Allow "Carnivore"
- Check console for errors

### Server won't start

- Verify Python venv exists at `../venv`
- Check `which python3` points to venv
- Test manually: `cd .. && source venv/bin/activate && python3 -m src.main`

### Health endpoint fails

- Ensure server is running on port 8000
- Check firewall isn't blocking localhost
- Verify `/api/v1/health` endpoint exists (see src/api/routes.py)

### Auto-launch not working

- Check plist exists: `ls ~/Library/LaunchAgents/ai.carnivore.menubar.plist`
  (a pre-Phase-9 install may still show `com.cloudecode.menubar.plist`
  instead, until this app has launched once since the upgrade and run its
  LaunchAgent migration - see "Auto-Launch" above)
- Validate plist: `plutil ~/Library/LaunchAgents/ai.carnivore.menubar.plist`
- Check launchctl: `launchctl list | grep carnivore`

## License

MIT (same as parent project)
