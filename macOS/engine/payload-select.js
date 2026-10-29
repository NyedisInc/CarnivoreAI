'use strict';

const nodeFs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const os = require('node:os');

const TREE_ARCH = { arm64: 'arm64', x64: 'x86_64' };

const TREE_ARCHES = ['arm64', 'x86_64'];

function payloadArch(processArch = process.arch) {
  const arch = TREE_ARCH[processArch];
  if (!arch) {
    throw new Error(`no engine payload for architecture '${processArch}'`);
  }
  return arch;
}

function payloadRoot(resourcesPath, processArch = process.arch) {
  return path.join(resourcesPath, 'payload', `payload-${payloadArch(processArch)}`);
}

const SYSTEM_SBIN = '/usr/sbin:/sbin';

function isExecutableFile(file, fsImpl) {
  try {
    if (!fsImpl.statSync(file).isFile()) return false;
    fsImpl.accessSync(file, nodeFs.constants.X_OK);
    return true;
  } catch (_) {
    return false;
  }
}

function resolvePayload(resourcesPath, processArch = process.arch, fsImpl = nodeFs) {
  if (!resourcesPath) return null;
  let root;
  try {
    root = payloadRoot(resourcesPath, processArch);
  } catch (_) {
    return null;
  }
  const pythonBinDir = path.join(root, 'python', 'bin');
  const binDir = path.join(root, 'bin');
  const python = path.join(pythonBinDir, 'python3');
  const tmux = path.join(binDir, 'tmux');
  if (!isExecutableFile(python, fsImpl) || !isExecutableFile(tmux, fsImpl)) return null;
  return { root, python, pythonBinDir, binDir, tmux };
}

const USER_TOOL_DIRS = ['/opt/homebrew/bin', '/usr/local/bin'];

function enginePath(payload, options = {}) {
  const parts = [payload.binDir, options.shellBinDir]
    .concat(String(options.inheritedPath || '').split(':'), USER_TOOL_DIRS, ['/usr/bin', '/bin'], SYSTEM_SBIN.split(':'));
  const seen = new Set();
  return parts.filter((dir) => dir && !seen.has(dir) && seen.add(dir)).join(':');
}

function stageTmux(tmux, stageDir) {
  try {
    const digest = sha256Of(tmux);
    const key = digest.slice(0, 16);
    const dest = path.join(stageDir, key, 'tmux');
    if (!(isExecutableFile(dest, nodeFs) && sha256Of(dest) === digest)) {
      if (nodeFs.existsSync(dest)) console.warn('payload: the staged tmux no longer matches its hash key; staging it again from the payload');
      nodeFs.mkdirSync(path.dirname(dest), { recursive: true });
      const tmp = `${dest}.${process.pid}.tmp`;
      nodeFs.copyFileSync(tmux, tmp);
      nodeFs.chmodSync(tmp, 0o755);
      nodeFs.renameSync(tmp, dest);
    }
    return dest;
  } catch (err) {
    console.warn(`payload: could not stage tmux (${err.message}); using the bundled copy`);
    return tmux;
  }
}

function sha256Of(file) {
  return crypto.createHash('sha256').update(nodeFs.readFileSync(file)).digest('hex');
}

function defaultPycacheDir() {
  return path.join(os.homedir(), 'Library', 'Caches', 'Carnivore', 'pycache');
}

function pycacheEnv(cacheDir = defaultPycacheDir(), fsImpl = nodeFs) {
  try {
    fsImpl.mkdirSync(cacheDir, { recursive: true, mode: 0o700 });
    fsImpl.accessSync(cacheDir, nodeFs.constants.W_OK | nodeFs.constants.X_OK);
    return { PYTHONPYCACHEPREFIX: cacheDir };
  } catch (err) {
    console.warn(`payload: no bytecode cache folder (${err.message}); bytecode writing is off`);
    return { PYTHONDONTWRITEBYTECODE: '1' };
  }
}

function applyPayloadEnv(payload, env, stageDir, cacheDir) {
  const tmux = stageDir ? stageTmux(payload.tmux, stageDir) : payload.tmux;
  const out = { ...env, CARNIVORE_BUNDLED_TMUX: tmux, CARNIVORE_PAYLOAD_PYTHON: payload.python, PYTHONNOUSERSITE: '1', ...pycacheEnv(cacheDir) };
  if (stageDir) out.CARNIVORE_TMUX_STAGE_DIR = stageDir;
  delete out.PYTHONHOME;
  delete out.PYTHONPATH;
  return out;
}

function payloadEngineEnv(payload, inherited, shellBinDir, stageDir, cacheDir) {
  const env = applyPayloadEnv(payload, inherited, stageDir, cacheDir);
  env.PATH = enginePath(payload, { inheritedPath: inherited.PATH, shellBinDir });
  return env;
}

module.exports = { payloadEngineEnv, payloadArch, payloadRoot, TREE_ARCHES, resolvePayload, enginePath, applyPayloadEnv, stageTmux, SYSTEM_SBIN, pycacheEnv, defaultPycacheDir };
