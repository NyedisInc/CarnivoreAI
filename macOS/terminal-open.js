
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { isAbsolutePath } = require('./terminal-scripts');
const { pickTmuxForSocket } = require('./engine/tmux-pick');
const { resolvePayload } = require('./engine/payload-select');

const TERMINAL_BUNDLE_IDS = Object.freeze([
  'com.apple.Terminal',
  'com.googlecode.iterm2',
  'com.mitchellh.ghostty',
  'com.github.wez.wezterm',
  'net.kovidgoyal.kitty',
  'dev.warp.Warp-Stable',
  'org.alacritty',
]);

const FALLBACK_BUNDLE_ID = 'com.apple.Terminal';

const SCRIPT_DIR_PREFIX = 'carnivore-term-';

const STALE_SCRIPT_AGE_MS = 60 * 60 * 1000;

/* WELL_KNOWN_PATHS */
const TMUX_WELL_KNOWN = Object.freeze([
  '/opt/homebrew/bin/tmux', '/usr/local/bin/tmux', '/opt/local/bin/tmux', '/usr/bin/tmux', '/bin/tmux',
]);

const CLAUDE_WELL_KNOWN = Object.freeze([
  '.local/bin/claude', '.claude/local/claude', '/opt/homebrew/bin/claude', '/usr/local/bin/claude',
]);

const LOGIN_SHELL_TIMEOUT_MS = 5000;

const HANDLER_TIMEOUT_MS = 5000;

const PROBE_TMUX = 'CARNIVORE_TMUX=';
const PROBE_CLAUDE = 'CARNIVORE_CLAUDE=';

function isSafeExecutable(candidate, deps) {
  if (!isAbsolutePath(candidate)) return false;
  try {
    const st = deps.fs.statSync(candidate);
    const ownerOk = st.uid === 0 || st.uid === deps.uid;
    return st.isFile() && ownerOk && (st.mode & 0o111) !== 0 && (st.mode & 0o022) === 0;
  } catch (error) {
    return false;
  }
}

function loginShell(deps) {
  return isSafeExecutable(deps.userShell, deps) ? deps.userShell : '/bin/zsh';
}

function parseProbeOutput(stdout) {
  const found = { tmux: null, claude: null };
  for (const line of String(stdout || '').split('\n')) {
    if (line.startsWith(PROBE_TMUX)) found.tmux = line.slice(PROBE_TMUX.length).trim() || null;
    if (line.startsWith(PROBE_CLAUDE)) found.claude = line.slice(PROBE_CLAUDE.length).trim() || null;
  }
  return found;
}

/* could not */
function resolveTools(deps, socketPath) {
  const probe = `printf '%s\\n' "${PROBE_TMUX}$(command -v tmux)" "${PROBE_CLAUDE}$(command -v claude)"`;
  return new Promise((resolve) => {
    deps.execFile(loginShell(deps), ['-l', '-c', probe], { timeout: LOGIN_SHELL_TIMEOUT_MS }, async (error, stdout) => {
      if (error) console.warn('[tray-terminal] login shell probe failed; using well-known paths:', error.message);
      const found = parseProbeOutput(error ? '' : stdout);
      const bundled = deps.payload && deps.payload.tmux ? [deps.payload.tmux] : [];
      const tmuxCandidates = bundled.concat([found.tmux], TMUX_WELL_KNOWN);
      const claudeCandidates = [found.claude].concat(
        CLAUDE_WELL_KNOWN.map((p) => (path.isAbsolute(p) ? p : path.join(deps.home, p)))
      );
      const usable = [...new Set(tmuxCandidates)].filter((p) => path.basename(String(p)) === 'tmux' && isSafeExecutable(p, deps));
      const live = socketPath && deps.fs.existsSync(socketPath) ? socketPath : null;
      const tmux = await pickTmuxForSocket(usable, live, deps);
      const claude = claudeCandidates.find((p) => isSafeExecutable(p, deps)) || 'claude';
      resolve({ tmux, claude, tmuxCandidates: usable });
    });
  });
}

/* private directory */
function writePrivateScript(contents, basename, deps) {
  const dir = deps.fs.mkdtempSync(path.join(deps.tmpdir, SCRIPT_DIR_PREFIX));
  deps.fs.chmodSync(dir, 0o700);
  const file = path.join(dir, basename);
  deps.fs.writeFileSync(file, contents, { mode: 0o700, flag: 'wx' });
  deps.fs.chmodSync(file, 0o700);
  return file;
}

function sweepStaleScripts(deps) {
  let removed = 0;
  let names;
  try {
    names = deps.fs.readdirSync(deps.tmpdir);
  } catch (error) {
    console.warn('[tray-terminal] could not list the temp dir for the sweep:', error.message);
    return 0;
  }
  for (const name of names) {
    if (!name.startsWith(SCRIPT_DIR_PREFIX)) continue;
    const full = path.join(deps.tmpdir, name);
    try {
      const st = deps.fs.lstatSync(full);
      if (!st.isDirectory() || st.uid !== deps.uid || deps.now - st.mtimeMs < STALE_SCRIPT_AGE_MS) continue;
      deps.fs.rmSync(full, { recursive: true, force: true });
      removed += 1;
    } catch (error) {
      console.warn('[tray-terminal] could not sweep a leftover script dir:', name, error.message);
    }
  }
  return removed;
}

/* could not be determined */
function detectHandlerBundleId(probePath, deps) {
  const jxa = [
    'ObjC.import("AppKit");',
    'var u = $.NSURL.fileURLWithPath($(' + JSON.stringify(probePath) + '));',
    'var a = $.NSWorkspace.sharedWorkspace.URLForApplicationToOpenURL(u);',
    'var b = a.isNil() ? $() : $.NSBundle.bundleWithURL(a).bundleIdentifier;',
    'b.isNil() ? "" : ObjC.unwrap(b);',
  ].join('\n');
  return new Promise((resolve) => {
    deps.execFile('osascript', ['-l', 'JavaScript', '-e', jxa], { timeout: HANDLER_TIMEOUT_MS }, (error, stdout) => {
      if (error) {
        console.warn('[tray-terminal] could not resolve the .command handler:', error.message);
        return resolve(null);
      }
      const id = String(stdout || '').trim() || null;
      if (id) console.log('[terminal-open] .command handler:', id);
      resolve(id);
    });
  });
}

function chooseTerminal(handlerBundleId) {
  if (handlerBundleId && TERMINAL_BUNDLE_IDS.includes(handlerBundleId)) {
    return { bundleId: handlerBundleId, usedFallback: false };
  }
  return { bundleId: FALLBACK_BUNDLE_ID, usedFallback: true };
}

async function openScriptInApp(contents, basename, bundleId, deps) {
  if (!TERMINAL_BUNDLE_IDS.includes(bundleId)) return { opened: false, bundleId: null, error: 'not a terminal app Carnivore knows' };
  let file;
  try {
    file = writePrivateScript(contents, basename, deps);
  } catch (error) {
    return { opened: false, bundleId: null, error: error.message };
  }
  return new Promise((resolve) => {
    deps.execFile('/usr/bin/open', ['-b', bundleId, file], { timeout: HANDLER_TIMEOUT_MS }, (error) => {
      if (error) deps.fs.rmSync(path.dirname(file), { recursive: true, force: true });
      resolve({ opened: !error, bundleId, error: error ? error.message : null });
    });
  });
}

/* nothing opened */
async function openScriptInTerminal(contents, basename, deps) {
  let file;
  try {
    file = writePrivateScript(contents, basename, deps);
  } catch (error) {
    return { opened: false, bundleId: null, handlerBundleId: null, usedFallback: false, error: error.message };
  }
  const handlerBundleId = await detectHandlerBundleId(file, deps);
  const choice = chooseTerminal(handlerBundleId);
  return new Promise((resolve) => {
    deps.execFile('/usr/bin/open', ['-b', choice.bundleId, file], { timeout: HANDLER_TIMEOUT_MS }, (error) => {
      if (error) {
        deps.fs.rmSync(path.dirname(file), { recursive: true, force: true });
      }
      resolve({
        opened: !error,
        bundleId: choice.bundleId,
        handlerBundleId,
        usedFallback: choice.usedFallback,
        error: error ? error.message : null,
      });
    });
  });
}

function liveDeps() {
  const info = os.userInfo();
  return {
    fs,
    execFile: require('child_process').execFile,
    spawn: require('child_process').spawn,
    tmpdir: os.tmpdir(),
    uid: process.getuid(),
    home: info.homedir,
    userShell: info.shell || null,
    payload: resolvePayload(process.resourcesPath || ''),
    now: Date.now(),
  };
}

module.exports = {
  TERMINAL_BUNDLE_IDS,
  FALLBACK_BUNDLE_ID,
  SCRIPT_DIR_PREFIX,
  STALE_SCRIPT_AGE_MS,
  isSafeExecutable,
  loginShell,
  parseProbeOutput,
  resolveTools,
  writePrivateScript,
  sweepStaleScripts,
  detectHandlerBundleId,
  chooseTerminal,
  openScriptInApp,
  openScriptInTerminal,
  liveDeps,
};
