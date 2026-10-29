
'use strict';

const VERSION_RE = /(\d+)\.(\d+)/;

function tmuxVersionKey(text) {
  const m = VERSION_RE.exec(String(text || ''));
  return m ? [Number(m[1]), Number(m[2])] : null;
}

function versionsMatch(client, server) {
  const a = tmuxVersionKey(client);
  const b = tmuxVersionKey(server);
  if (a || b) return !!a && !!b && a[0] === b[0] && a[1] === b[1];
  const strip = (s) => String(s || '').trim().replace(/^tmux /, '');
  return !!client && strip(client) === strip(server);
}

function query(bin, args, deps) {
  return new Promise((resolve) => {
    deps.execFile(bin, args, { timeout: 3000 }, (error, stdout, stderr) => {
      resolve({ error: error || null, stdout: String(stdout || ''), stderr: String(stderr || (error && error.message) || '') });
    });
  });
}

async function serverVersion(bin, socketPath, deps) {
  const r = await query(bin, ['-f', '/dev/null', '-S', socketPath, 'display-message', '-p', '#{version}'], deps);
  if (!r.error && r.stdout.trim()) return { state: 'answered', version: r.stdout.trim() };
  if (/protocol version mismatch/i.test(r.stderr)) return { state: 'mismatch', version: null };
  if (/no server running|error connecting|No such file/i.test(r.stderr)) return { state: 'no_server', version: null };
  return { state: 'unknown', version: null };
}

async function pickTmuxForSocket(candidates, socketPath, deps) {
  if (!candidates.length) return null;
  if (!socketPath || candidates.length === 1) return candidates[0];
  let state = 'unknown';
  let server = null;
  for (const bin of candidates) {
    ({ state, version: server } = await serverVersion(bin, socketPath, deps));
    if (state === 'answered' || state === 'no_server') break;
  }
  if (state !== 'answered') return candidates[0];
  for (const bin of candidates) {
    const got = await query(bin, ['-V'], deps);
    if (!got.error && versionsMatch(got.stdout.trim().replace(/^tmux /, ''), server)) return bin;
  }
  return candidates[0];
}

module.exports = { tmuxVersionKey, versionsMatch, serverVersion, pickTmuxForSocket };
