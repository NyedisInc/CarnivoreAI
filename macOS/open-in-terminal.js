
'use strict';

const scripts = require('./terminal-scripts');
const terminalOpen = require('./terminal-open');
const confirm = require('./terminal-confirm');
const { senderAllowed } = require('./desktop-settings');

const CHANNEL = 'carnivore:open-in-terminal';
const PREFERENCES_ROUTE = '/api/v1/preferences';
const APP_BUNDLE_IDS = Object.freeze({
  terminal: 'com.apple.Terminal',
  iterm2: 'com.googlecode.iterm2',
  ghostty: 'com.mitchellh.ghostty',
  kitty: 'net.kovidgoyal.kitty',
  wezterm: 'com.github.wez.wezterm',
});
const DEFAULT_APP = 'terminal';
// eslint-disable-next-line no-control-regex
const SESSION_ID_RE = /^(?:ses_[A-Za-z0-9_.-]{1,120}|adopted:[^\u0000-\u001f\u007f]{1,200})$/;
const CUSTOM_SETTLE_MS = 1500;
const REASONS = Object.freeze({ ok: 'ok', remote: 'remote', notRunning: 'not_running', cancelled: 'cancelled', failed: 'failed' });

function validateAttachArgv(argv, deps, readOnly) {
  const flags = readOnly ? ['-r'] : ['-f', 'ignore-size'];
  const want = 6 + flags.length;
  if (!Array.isArray(argv) || argv.length !== want || !argv.every((part) => typeof part === 'string')) {
    return { ok: false, error: 'the attach command has an unexpected shape' };
  }
  const [tmux, dashL, socket, verb, ...rest] = argv;
  const tail = rest.slice(0, flags.length);
  const target = rest.slice(flags.length);
  const shapeOk = dashL === '-L' && verb === 'attach-session' && tail.every((part, i) => part === flags[i])
    && target[0] === '-t' && target[1].startsWith('=') && scripts.isValidTmuxName(target[1].slice(1))
    && scripts.SOCKET_NAME_RE.test(socket);
  if (!shapeOk) return { ok: false, error: 'the attach command has an unexpected shape' };
  if (!/(^|\/)tmux$/.test(tmux) || !terminalOpen.isSafeExecutable(tmux, deps)) {
    return { ok: false, error: 'the tmux program in the attach command is not a safe executable' };
  }
  return { ok: true, error: null };
}

function splitTemplate(template) {
  // eslint-disable-next-line no-control-regex
  if (typeof template !== 'string' || /[\u0000-\u001f\u007f]/.test(template)) return { ok: false, words: [], error: 'the custom command is empty or has control characters' };
  const words = [];
  let current = null;
  let quote = null;
  const chars = Array.from(template);
  for (let i = 0; i < chars.length; i += 1) {
    const ch = chars[i];
    if (quote === "'") {
      if (ch === "'") quote = null; else current += ch;
    } else if (quote === '"') {
      if (ch === '"') quote = null;
      else if (ch === '\\' && i + 1 < chars.length && '"\\$`'.includes(chars[i + 1])) { i += 1; current += chars[i]; }
      else current += ch;
    } else if (ch === "'" || ch === '"') {
      quote = ch;
      if (current === null) current = '';
    } else if (ch === '\\') {
      if (i + 1 >= chars.length) return { ok: false, words: [], error: 'the custom command ends with a backslash' };
      i += 1;
      current = (current === null ? '' : current) + chars[i];
    } else if (ch === ' ' || ch === '\t') {
      if (current !== null) words.push(current);
      current = null;
    } else {
      current = (current === null ? '' : current) + ch;
    }
  }
  if (quote) return { ok: false, words: [], error: 'the custom command has an unclosed quote' };
  if (current !== null) words.push(current);
  return words.length ? { ok: true, words, error: null } : { ok: false, words: [], error: 'the custom command is empty' };
}

function customLaunch(template, attachArgv) {
  const split = splitTemplate(template);
  if (!split.ok) return { ok: false, file: null, args: [], error: split.error };
  const [first, ...rest] = split.words;
  const file = first === 'open' ? '/usr/bin/open' : first;
  if (!scripts.isAbsolutePath(file)) return { ok: false, file: null, args: [], error: 'the custom command must start with open or an absolute path' };
  return { ok: true, file, args: [...rest, ...attachArgv], error: null };
}

/* could not be read */
async function readTerminalPrefs(api) {
  const result = await api.getAuthed(PREFERENCES_ROUTE);
  const values = result && result.reachable && result.data ? result.data.values : null;
  if (typeof values !== 'object' || values === null) return null;
  return {
    app: typeof values.desktop_terminal_app === 'string' ? values.desktop_terminal_app : DEFAULT_APP,
    custom: typeof values.desktop_terminal_custom === 'string' ? values.desktop_terminal_custom : '',
  };
}

function runCustom(file, args, deps) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (!settled) { settled = true; resolve(result); }
    };
    const timer = setTimeout(() => finish({ opened: true, error: null }), CUSTOM_SETTLE_MS);
    let child;
    try {
      child = deps.spawn(file, args, { detached: true, stdio: 'ignore' });
    } catch (error) {
      clearTimeout(timer);
      finish({ opened: false, error: error.message });
      return;
    }
    child.on('error', (error) => { clearTimeout(timer); finish({ opened: false, error: error.message }); });
    child.on('exit', (code, signal) => {
      clearTimeout(timer);
      if (code !== 0 && settled) console.warn('[open-in-terminal] the custom command ended with', code === null ? signal : code);
      finish(code === 0 ? { opened: true, error: null } : { opened: false, error: `the command exited with ${code === null ? signal : code}` });
    });
    child.unref();
  });
}

function createOpenInTerminal(deps) {
  const result = (opened, reason, error) => ({ opened, error: error || null, reason });

  async function fetchArgv(api, sessionId, readOnly) {
    const route = `/api/v1/sessions/${encodeURIComponent(sessionId)}/attach-command${readOnly ? '?read_only=true' : ''}`;
    const answer = await api.getAuthed(route);
    if (answer.reachable && answer.data && Array.isArray(answer.data.argv)) return { argv: answer.data.argv, reason: REASONS.ok, error: null };
    if (answer.status === 404 || answer.status === 409) return { argv: null, reason: REASONS.notRunning, error: null };
    return { argv: null, reason: REASONS.failed, error: answer.error || 'the server did not answer' };
  }

  async function openCustom(prefs, argv, live) {
    const launch = customLaunch(prefs.custom, argv);
    if (!launch.ok) return result(false, REASONS.failed, launch.error);
    const t = await deps.loadTranslator();
    const approved = await confirm.confirmCustom({
      argv: [launch.file, ...launch.args], hashParts: [launch.file, ...launch.args.slice(0, -1)],
      dir: deps.dataDir(), dialog: deps.dialog, t, fs: live.fs,
    });
    if (!approved) return result(false, REASONS.cancelled);
    const ran = await runCustom(launch.file, launch.args, { spawn: live.spawn });
    return ran.opened ? result(true, REASONS.ok) : result(false, REASONS.failed, ran.error);
  }

  async function resolve(sessionId, readOnly) {
    const fail = (reason, error) => ({ argv: null, api: null, live: null, failure: result(false, reason, error) });
    if (typeof sessionId === 'string' && sessionId.startsWith('remote:')) return fail(REASONS.remote);
    if (typeof sessionId !== 'string' || !SESSION_ID_RE.test(sessionId)) return fail(REASONS.failed, 'not a session id');
    const api = deps.api();
    if (!api) return fail(REASONS.failed, 'the server is not reachable');
    const live = deps.live ? deps.live() : terminalOpen.liveDeps();
    const fetched = await fetchArgv(api, sessionId, readOnly);
    if (!fetched.argv) return fail(fetched.reason, fetched.error);
    const checked = validateAttachArgv(fetched.argv, live, readOnly);
    if (!checked.ok) return fail(REASONS.failed, checked.error);
    return { argv: fetched.argv, api, live, failure: null };
  }

  return {
    async open(sessionId, options) {
      try {
        const readOnly = Boolean(options && options.readOnly);
        const found = await resolve(sessionId, readOnly);
        if (!found.argv) return found.failure;
        const prefs = await readTerminalPrefs(found.api);
        if (!prefs) return result(false, REASONS.failed, 'the terminal setting could not be read');
        if (prefs.app === 'custom') return await openCustom(prefs, found.argv, found.live);
        const bundleId = APP_BUNDLE_IDS[prefs.app];
        if (!bundleId) return result(false, REASONS.failed, 'unknown terminal app');
        const script = scripts.buildAttachScript({ argv: found.argv, label: sessionId, tmuxTmpdir: process.env.TMUX_TMPDIR || null });
        const opened = await terminalOpen.openScriptInApp(script, 'carnivore-attach.command', bundleId, found.live);
        return opened.opened ? result(true, REASONS.ok) : result(false, REASONS.failed, opened.error);
      } catch (error) {
        console.warn('[open-in-terminal] failed:', error && error.message);
        return result(false, REASONS.failed, String((error && error.message) || error));
      }
    },

    async attachArgv(sessionId) {
      try {
        const found = await resolve(sessionId, false);
        return found.argv ? { argv: found.argv, reason: REASONS.ok, error: null } : { argv: null, reason: found.failure.reason, error: found.failure.error };
      } catch (error) {
        return { argv: null, reason: REASONS.failed, error: String((error && error.message) || error) };
      }
    },
  };
}

function registerOpenInTerminal(deps) {
  const opener = createOpenInTerminal(deps);
  deps.ipcMain.handle(CHANNEL, async (event, sessionId) => {
    if (!senderAllowed(event, deps)) return null;
    return opener.open(sessionId);
  });
  return opener;
}

module.exports = {
  CHANNEL, SESSION_ID_RE, APP_BUNDLE_IDS, REASONS, validateAttachArgv, splitTemplate, customLaunch, readTerminalPrefs,
  runCustom, createOpenInTerminal, registerOpenInTerminal,
};
