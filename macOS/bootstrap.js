/* Application Support */

const { spawn, execFile, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { ensureDirMode, PRIVATE_DIR_MODE } = require('./engine/fs-perms');
const { resolvePayload } = require('./engine/payload-select');
const { classifyPython, tooNewMessage, buildPipInstallArgs, venvNeedsRebuild, MIN_MINOR } = require('./python-lock');


const MIN_PYTHON_MAJOR = 3;
const MIN_PYTHON_MINOR = MIN_MINOR;

const SAFE_PATH = [
  '/opt/homebrew/bin',
  '/usr/local/bin',
  '/usr/bin',
  '/bin',
  '/usr/sbin',
  '/sbin',
].join(':');

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';


/* padding */
function base32Encode(buffer) {
  let bits = 0;
  let value = 0;
  let output = '';
  for (const byte of buffer) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      output += BASE32_ALPHABET[(value >>> (bits - 5)) & 0x1f];
      bits -= 5;
    }
  }
  if (bits > 0) {
    output += BASE32_ALPHABET[(value << (5 - bits)) & 0x1f];
  }
  return output;
}

function spawnEnv(extra = {}) {
  return {
    ...process.env,
    PATH: `${SAFE_PATH}:${process.env.PATH || ''}`,
    ...extra,
  };
}

function runCommand(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      env: spawnEnv(opts.env),
      cwd: opts.cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => {
      const s = d.toString();
      stdout += s;
      if (opts.onStdout) opts.onStdout(s);
    });
    child.stderr.on('data', (d) => {
      const s = d.toString();
      stderr += s;
      if (opts.onStderr) opts.onStderr(s);
    });
    child.on('error', (err) => {
      resolve({ code: -1, stdout, stderr: stderr + `\n[spawn error] ${err.message}` });
    });
    child.on('exit', (code) => {
      resolve({ code: code ?? -1, stdout, stderr });
    });
  });
}

async function findSuitablePython() {
  const candidates = [
    '/opt/homebrew/bin/python3.12',
    '/opt/homebrew/bin/python3.13',
    '/opt/homebrew/bin/python3.14',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3.12',
    '/usr/local/bin/python3.13',
    '/usr/local/bin/python3.14',
    '/usr/local/bin/python3',
    path.join(os.homedir(), '.pyenv', 'shims', 'python3'),
    '/usr/bin/python3',
  ];

  let tooNew = null;
  for (const candidate of candidates) {
    if (!fs.existsSync(candidate)) continue;
    const { code, stdout, stderr } = await runCommand(candidate, ['--version']);
    if (code !== 0) continue;
    const { verdict, version } = classifyPython((stdout + stderr).trim());
    if (verdict === 'ok') return { path: candidate, version };
    if (verdict === 'too-new' && !tooNew) tooNew = { path: candidate, version, tooNew: true };
  }
  return tooNew;
}

function copyRecursive(src, dest) {
  let copied = 0;
  if (!fs.existsSync(src)) return 0;
  if (!fs.existsSync(dest)) fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copied += copyRecursive(s, d);
    } else if (!fs.existsSync(d)) {
      fs.copyFileSync(s, d);
      copied++;
    }
  }
  return copied;
}

function sha256File(filePath) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(filePath));
  return hash.digest('hex');
}

function atomicWriteFile(filePath, content) {
  const tmp = filePath + '.tmp';
  fs.writeFileSync(tmp, content, 'utf8');
  fs.renameSync(tmp, filePath);
}

function isExecutable(p) {
  try {
    fs.accessSync(p, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function secureEnvFile(envPath) {
  try {
    if ((fs.statSync(envPath).mode & 0o777) !== 0o600) fs.chmodSync(envPath, 0o600);
    return true;
  } catch (err) {
    if (err.code !== 'ENOENT') console.warn(`[bootstrap] could not set .env to 0600: ${err.message}`);
    return false;
  }
}


function generateEnvFile({ envExamplePath, envOutPath, defaultWorkingDir, logDirectory }) {
  if (!fs.existsSync(envExamplePath)) {
    throw new Error(`.env.example not found at ${envExamplePath}`);
  }

  const totpSecret = base32Encode(crypto.randomBytes(20));
  const jwtSecret = crypto.randomBytes(32).toString('hex');

  const lines = fs.readFileSync(envExamplePath, 'utf8').split('\n');
  const out = lines.map((line) => {
    if (line.startsWith('TOTP_SECRET=')) return `TOTP_SECRET=${totpSecret}`;
    if (line.startsWith('JWT_SECRET=')) return `JWT_SECRET=${jwtSecret}`;
    if (line.startsWith('DEFAULT_WORKING_DIR=')) return `DEFAULT_WORKING_DIR=${defaultWorkingDir}`;
    if (line.startsWith('LOG_DIRECTORY=')) return `LOG_DIRECTORY=${logDirectory}`;
    return line;
  });

  atomicWriteFile(envOutPath, out.join('\n'));
  return { codeKeyLen: totpSecret.length, signKeyLen: jwtSecret.length };
}


const RESYNC_ALLOWLIST = [
  { name: 'src', isDir: true, keep: ['__pycache__'] },
  { name: 'client', isDir: true },
  { name: 'features', isDir: true },
  { name: 'requirements.txt', isDir: false },
  { name: 'requirements.lock', isDir: false },
  { name: 'setup_auth.py', isDir: false },
  { name: 'config.example.json', isDir: false },
  { name: '.env.example', isDir: false },
  // state directory
  { name: 'nuke.sh', isDir: false },
  { name: 'scripts/session_journal.py', isDir: false },
  { name: 'scripts/resolve-port.sh', isDir: false },
  { name: 'scripts/upgrade_lib/upgrade_rollback_common.sh', isDir: false },
];

function rsyncDir(srcDir, dstDir, keep = []) {
  fs.mkdirSync(dstDir, { recursive: true });
  const result = spawnSync(
    '/usr/bin/rsync',
    ['-a', '--delete', ...keep.map((n) => `--exclude=${n}`), `${srcDir}/`, `${dstDir}/`],
    { encoding: 'utf8' }
  );
  if (result.status !== 0) {
    return {
      ok: false,
      code: result.status,
      stderr: (result.stderr || '').trim(),
    };
  }
  return { ok: true };
}

function syncBundledAssets({ serverDir, bundleResourcesDir, isPackaged }) {
  if (!isPackaged) {
    console.log('[bootstrap] dev mode — skipping bundled-asset resync');
    return { ok: true, summary: 'dev-mode skip' };
  }

  if (!fs.existsSync(bundleResourcesDir)) {
    return {
      ok: false,
      details: `bundleResourcesDir does not exist: ${bundleResourcesDir}`,
    };
  }

  fs.mkdirSync(serverDir, { recursive: true });

  const t0 = Date.now();
  const synced = [];
  const skipped = [];

  for (const item of RESYNC_ALLOWLIST) {
    const src = path.join(bundleResourcesDir, item.name);
    const dst = path.join(serverDir, item.name);

    if (!fs.existsSync(src)) {
      skipped.push(`${item.name} (not in bundle)`);
      continue;
    }

    if (item.isDir) {
      const res = rsyncDir(src, dst, item.keep || []);
      if (!res.ok) {
        return {
          ok: false,
          details: `rsync failed for ${item.name}/ (exit ${res.code}): ${res.stderr.slice(-400)}`,
        };
      }
      synced.push(`${item.name}/`);
    } else {
      // already exists
      try {
        fs.mkdirSync(path.dirname(dst), { recursive: true });
        fs.copyFileSync(src, dst);
        synced.push(item.name);
      } catch (err) {
        return {
          ok: false,
          details: `copy failed for ${item.name}: ${err.message}`,
        };
      }
    }
  }

  const elapsed = Date.now() - t0;
  const summary =
    `resynced ${synced.length} items in ${elapsed}ms ` +
    `[${synced.join(', ')}]` +
    (skipped.length ? ` skipped [${skipped.join(', ')}]` : '');
  console.log(`[bootstrap] ${summary}`);
  return { ok: true, summary };
}


const USER_THEMES_README = `# Carnivore: User Themes

Drop your custom themes in this directory as subfolders, one per theme.
Each theme is a folder named after the theme \`id\`, containing a
\`theme.json\` manifest and (optionally) an \`effects.js\` for runtime FX.

## Discovery

The server scans this dir on every \`GET /api/v1/themes\` call. No restart
needed — just refresh the browser after dropping a new theme in.

If a user theme has the same \`id\` as a bundled theme, the bundled one
wins and the user theme is skipped with a server-log warning.

## Schema

A minimal \`theme.json\`:

\`\`\`json
{
  "id": "neon",
  "name": "Neon",
  "description": "Pink-on-black retro arcade vibe.",
  "author": "you",
  "version": "1.0.0",
  "cssVars": {
    "--color-bg": "#0a0014",
    "--color-fg": "#ff00ff",
    "--color-accent": "#00ffff",
    "--color-border": "#330033"
  },
  "xterm": {
    "background": "#0a0014",
    "foreground": "#ff00ff",
    "cursor": "#00ffff"
  },
  "effects": "effects.js"
}
\`\`\`

## Fields

- \`id\` — must match the folder name. Mismatched manifests are skipped.
- \`name\`, \`description\` — shown in the theme selector.
- \`cssVars\` — map of CSS custom-property name to value, applied to \`:root\`.
- \`xterm\` — xterm.js theme object (background/foreground/ANSI palette).
- \`effects\` — optional filename of a JS module relative to the theme dir.
  First time a theme with effects is applied, the UI prompts for consent
  (Allow once / Always / Never). Choices persist in localStorage.

## Security

Theme assets are served unauth at \`http://<server>/themes/<id>/<file>\`.
Do NOT put secrets in \`theme.json\` or \`effects.js\`. Same threat model
as any static resource on the LAN-only deployment.
`;

function provisionUserThemesDir(userDataDir) {
  const dir = path.join(userDataDir, 'themes');
  try {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
      console.log(`[bootstrap] created user themes dir: ${dir}`);
    }
    const readmePath = path.join(dir, 'README.md');
    if (!fs.existsSync(readmePath)) {
      fs.writeFileSync(readmePath, USER_THEMES_README, 'utf8');
      console.log(`[bootstrap] dropped user themes README: ${readmePath}`);
    }
    return { ok: true, dir };
  } catch (e) {
    console.warn(`[bootstrap] could not provision user themes dir: ${e.message}`);
    return { ok: false, dir, error: e.message };
  }
}


const VERSION_FILE_HEADER =
  '# GENERATED FROM THE GIT TAG AT RELEASE TIME. DO NOT EDIT BY HAND.\n' +
  '# See src/core/version.py for the resolution order.\n';

/* CLOUDE_APP_VERSION */
function writeVersionStamp(serverDir, version) {
  const value = String(version || '').trim();
  if (!value) return false;
  try {
    fs.writeFileSync(
      path.join(serverDir, 'VERSION'),
      `${VERSION_FILE_HEADER}${value}\n`,
      'utf8'
    );
    console.log(`[bootstrap] stamped VERSION=${value}`);
    return true;
  } catch (err) {
    console.warn(`[bootstrap] could not stamp VERSION: ${err.message}`);
    return false;
  }
}


async function bootstrapIfNeeded({
  serverDir, bundleResourcesDir, isPackaged, onStateChange, appVersion,
}) {
  const emit = (state) => {
    if (onStateChange) {
      try { onStateChange(state); } catch (_) {  }
    }
  };

  const packaged = typeof isPackaged === 'boolean'
    ? isPackaged
    : /\.app\/Contents\/Resources\/?$/.test(bundleResourcesDir || '');

  emit('checking');

  const payload = resolvePayload(bundleResourcesDir);

  ensureDirMode(serverDir, PRIVATE_DIR_MODE, { log: (message) => console.warn(message) });

  const python = payload ? null : await findSuitablePython();
  if (!payload && !python) {
    return {
      status: 'python-missing',
      freshInstall: false,
      details: `Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ not found on PATH.`,
    };
  }
  if (!payload && python.tooNew) {
    return {
      status: 'python-too-new',
      freshInstall: false,
      details: tooNewMessage(python.version),
    };
  }
  if (payload) console.log(`[bootstrap] engine payload: ${payload.root}`);
  else console.log(`[bootstrap] Python found: ${python.path} (${python.version})`);

  provisionUserThemesDir(path.dirname(serverDir));

  // Application Support
  // already exists
  {
    emit('syncing-assets');
    fs.mkdirSync(serverDir, { recursive: true });
    const sync = syncBundledAssets({
      serverDir, bundleResourcesDir, isPackaged: true
    });
    if (!sync.ok) {
      return {
        status: 'error',
        freshInstall: false,
        details: `asset resync failed: ${sync.details}`,
      };
    }
    if (packaged) {
      writeVersionStamp(serverDir, appVersion);
    }
  }

  const venvPython = path.join(serverDir, 'venv', 'bin', 'python3');
  const envPath = path.join(serverDir, '.env');
  const depsHashPath = path.join(serverDir, '.deps-hash');
  const lockPath = path.join(serverDir, 'requirements.lock');
  const configPath = path.join(serverDir, 'config.json');

  const fastPathOk = (
    (payload || isExecutable(venvPython)) &&
    fs.existsSync(envPath) &&
    /^TOTP_SECRET=.+$/m.test(fs.readFileSync(envPath, 'utf8')) &&
    fs.existsSync(configPath) &&
    (payload || (
      fs.existsSync(lockPath) &&
      fs.existsSync(depsHashPath) &&
      fs.readFileSync(depsHashPath, 'utf8').trim() === sha256File(lockPath)
    ))
  );

  if (fastPathOk) {
    secureEnvFile(envPath);
    emit('ready');
    return { status: 'ready', freshInstall: false };
  }

  emit('preparing');

  try {
    if (!fs.existsSync(serverDir)) {
      fs.mkdirSync(serverDir, { recursive: true });
    }

    emit('copying-files');
    const firstRunResources = RESYNC_ALLOWLIST;
    for (const item of firstRunResources) {
      const src = path.join(bundleResourcesDir, item.name);
      const dst = path.join(serverDir, item.name);
      if (!fs.existsSync(src)) {
        console.warn(`[bootstrap] bundled resource missing (skipping): ${src}`);
        continue;
      }
      if (item.isDir) {
        const n = copyRecursive(src, dst);
        if (n > 0) console.log(`[bootstrap] copied ${n} files into ${item.name}/`);
      } else if (!fs.existsSync(dst)) {
        fs.copyFileSync(src, dst);
        console.log(`[bootstrap] copied ${item.name}`);
      }
    }

    const venvDir = path.join(serverDir, 'venv');
    if (!payload) {
      if (isExecutable(venvPython)) {
        const probe = await runCommand(venvPython, ['--version']);
        if (venvNeedsRebuild(probe.code, `${probe.stdout}${probe.stderr}`)) {
          console.log('[bootstrap] venv interpreter outside the proven range, rebuilding');
          fs.rmSync(venvDir, { recursive: true, force: true });
          fs.rmSync(depsHashPath, { force: true });
        }
      }
      if (!isExecutable(venvPython)) {
        emit('creating-venv');
        console.log(`[bootstrap] creating venv at ${venvDir}`);
        const { code, stderr } = await runCommand(python.path, ['-m', 'venv', venvDir]);
        if (code !== 0 || !isExecutable(venvPython)) {
          return {
            status: 'error',
            freshInstall: false,
            details: `python3 -m venv failed (exit ${code}):\n${stderr.slice(-600)}`,
          };
        }
      }

      if (!fs.existsSync(lockPath)) {
        return {
          status: 'error',
          freshInstall: false,
          details: `requirements.lock missing after copy step: bundled resource not found at ${path.join(bundleResourcesDir, 'requirements.lock')}`,
        };
      }
      const currentHash = sha256File(lockPath);
      const previousHash = fs.existsSync(depsHashPath)
        ? fs.readFileSync(depsHashPath, 'utf8').trim()
        : '';
      if (currentHash !== previousHash) {
        emit('installing-deps');
        console.log('[bootstrap] installing pip requirements (this may take 60-120s on first run)');
        const pipPath = path.join(venvDir, 'bin', 'pip');
        const { code, stderr } = await runCommand(
          pipPath,
          buildPipInstallArgs(lockPath),
          {
            onStdout: (chunk) => {
              for (const line of chunk.split('\n')) {
                if (line.trim()) console.log(`[pip] ${line.trim()}`);
              }
            },
            onStderr: (chunk) => {
              for (const line of chunk.split('\n')) {
                if (line.trim()) console.log(`[pip!] ${line.trim()}`);
              }
            },
          }
        );
        if (code !== 0) {
          return {
            status: 'error',
            freshInstall: false,
            details: `pip install failed (exit ${code}):\n${stderr.slice(-600)}`,
          };
        }
        fs.writeFileSync(depsHashPath, currentHash, 'utf8');
        console.log(`[bootstrap] deps-hash written: ${currentHash.slice(0, 12)}...`);
      }
    }

    let freshInstall = false;
    if (!fs.existsSync(envPath)) {
      emit('generating-secrets');
      const defaultWorkingDir = path.join(os.homedir(), 'carnivore-projects');
      const logDirectory = path.join(os.homedir(), 'Library', 'Logs', 'cloude-code');

      // DEFAULT_WORKING_DIR
      for (const d of [defaultWorkingDir, logDirectory]) {
        try {
          if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
        } catch (e) {
          console.warn(`[bootstrap] could not create ${d}: ${e.message}`);
        }
      }

      const envExamplePath = path.join(serverDir, '.env.example');
      const { codeKeyLen, signKeyLen } = generateEnvFile({
        envExamplePath,
        envOutPath: envPath,
        defaultWorkingDir,
        logDirectory,
      });
      console.log(`[bootstrap] .env generated (TOTP_SECRET len ${codeKeyLen}, JWT_SECRET len ${signKeyLen})`);
      freshInstall = true;
    }

    if (!fs.existsSync(configPath)) {
      emit('generating-config');
      const exampleConfig = path.join(serverDir, 'config.example.json');
      if (!fs.existsSync(exampleConfig)) {
        return {
          status: 'error',
          freshInstall: false,
          details: `config.example.json missing after copy — bundled resource absent`,
        };
      }
      fs.copyFileSync(exampleConfig, configPath);
      console.log('[bootstrap] config.json created from example');
    }

    secureEnvFile(envPath);
    emit('ready');
    return { status: 'ready', freshInstall };
  } catch (err) {
    console.error('[bootstrap] unhandled error:', err);
    return {
      status: 'error',
      freshInstall: false,
      details: err && err.stack ? err.stack : String(err),
    };
  }
}

module.exports = {
  bootstrapIfNeeded,
  secureEnvFile,
  base32Encode,
  generateEnvFile,
  findSuitablePython,
  sha256File,
  syncBundledAssets,
  provisionUserThemesDir,
  writeVersionStamp,
  VERSION_FILE_HEADER,
  RESYNC_ALLOWLIST,
};
