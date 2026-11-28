const { exec, execFile } = require('child_process');
const portTrust = require('./tray-menu/port-trust');
const path = require('path');
const { persistBindHost } = require('./bind-settings');
const http = require('http');
const { app } = require('electron');
const net = require('net');
const fs = require('fs');
const os = require('os');
const { currentTotp } = require('./totp');
const { readEnvValue, validateEnvFile } = require('./env-file');
const devProvisioning = require('./dev-provisioning');
const { terminateProcess, isAlive } = require('./process-teardown');
const { decideAdoption } = require('./adoption-decision');
const { decideLifecycleAction } = require('./ownership-policy');
const EXPOSURE_REFRESH_EVERY = 4;
const HEALTH_COALESCE_MS = 250;
const NETIF_CACHE_TTL_MS = 2000;

function httpGetJson(url, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (err, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err) reject(err); else resolve(value);
    };
    const req = http.get(url, (res) => {
      const status = res.statusCode || 0;
      if (status < 200 || status >= 300) {
        res.resume();
        finish(new Error(`HTTP ${status}`));
        return;
      }
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        try {
          finish(null, JSON.parse(text));
        } catch (_) {
          finish(null, text);
        }
      });
      res.on('error', (err) => finish(err));
    });
    const timer = setTimeout(() => {
      const err = new Error(`request timed out after ${timeoutMs}ms`);
      req.destroy(err);
      finish(err);
    }, timeoutMs);
    if (timer.unref) timer.unref();
    req.on('error', (err) => finish(err));
  });
}
const { createSupervisor, SUPERVISOR_RESTART } = require('./supervisor-policy');
const { createSlowRetry } = require('./supervisor-slow-retry');
const setupVerdict = require('./setup-verdict');
const DOWN_AFTER_MISSES = 3;
const { resolvePublishedUrl, resolveAppWindowUrl } = require('./published-url');
const { appendWithRotation } = require('./log-rotation');
const { appendEngineLog } = require('./engine/detached-spawn');
const { resolvePayload, payloadEngineEnv } = require('./engine/payload-select');
const engineLifecycle = require('./engine/engine-lifecycle');

const DEFAULT_BIND_HOST = '0.0.0.0';

const DEFAULT_PORT = 8000;

const { listBindableIps, isTailscaleIp } = require('./network-interfaces');
const { ensureVerified: ensureVerifiedCloudflared } = require('./cloudflared-pin');


class ServerManager {
  constructor() {
    this.process = null;
    this.processPid = null;
    this.ownedProcess = false;
    this.adoptedVersion = null;
    this.engineRecord = null;

    this.startBlockedReason = null;

    this.supervisor = createSupervisor();
    this.supervisorTimer = null;
    this.quitting = false;
    this.slowRetry = createSlowRetry(this);
    this.serviceOwnsEngine = () => false;

    this.stopRequested = false;
    this.lastExitUnexpected = false;
    this.lastExit = null;

    if (app.isPackaged) {
      this.baseDir = path.join(app.getPath('userData'), 'server');
      this.appResourcesPath = path.join(app.getAppPath(), '..');
    } else {
      this.baseDir = path.join(app.getPath('userData'), 'server');
      this.appResourcesPath = this.baseDir;
    }

    this.pythonPath = this.findPython();
    this.payload = resolvePayload(this.appResourcesPath);
    if (this.payload) this.pythonPath = this.payload.python;
    const logDir = path.join(app.getPath('userData'), 'logs');
    if (!fs.existsSync(logDir)) {
      fs.mkdirSync(logDir, { recursive: true });
    }
    this.logFile = path.join(logDir, 'server.log');
    this.state = 'stopped';
    this.startTime = null;

    this.settingsPath = path.join(app.getPath('userData'), 'menubar-settings.json');
    this._settings = this._loadSettings();

    // and the real
    this.reportedBind = null;
    this.reportedSetupStatus = null;

    this._fileCache = new Map();
    this._localSetupCache = null;
    this._netIfCache = null;
    this._healthInFlight = new Map();
    this.lastHealth = null;
    this.lastHealthAt = 0;
    this.lastHealthPort = null;
  }

  _readCachedFile(filePath) {
    let st;
    try {
      st = fs.statSync(filePath);
    } catch (err) {
      if (this._fileCache) this._fileCache.delete(filePath);
      return { exists: false, text: null, parsed: null, parseError: null, error: err };
    }
    if (!this._fileCache) this._fileCache = new Map();
    const hit = this._fileCache.get(filePath);
    if (hit && hit.mtimeMs === st.mtimeMs && hit.size === st.size && hit.ino === st.ino) {
      return hit;
    }
    let text;
    try {
      text = fs.readFileSync(filePath, 'utf8');
    } catch (err) {
      this._fileCache.delete(filePath);
      return { exists: true, text: null, parsed: null, parseError: null, error: err };
    }
    const entry = {
      exists: true,
      text,
      parsed: undefined,
      parseError: null,
      envValues: new Map(),
      mtimeMs: st.mtimeMs,
      size: st.size,
      ino: st.ino,
      error: null,
    };
    this._fileCache.set(filePath, entry);
    return entry;
  }

  _readCachedJson(filePath) {
    const entry = this._readCachedFile(filePath);
    if (!entry.exists || entry.text === null) return null;
    if (entry.parsed === undefined && !entry.parseError) {
      try {
        entry.parsed = JSON.parse(entry.text);
      } catch (err) {
        entry.parseError = err;
        entry.parsed = null;
      }
    }
    return entry.parseError ? null : entry.parsed;
  }

  _readCachedEnvValue(key) {
    const entry = this._readCachedFile(path.join(this.baseDir, '.env'));
    if (!entry.exists) return { exists: false, value: null, error: entry.error };
    if (entry.text === null) return { exists: true, value: null, error: entry.error };
    if (!entry.envValues) entry.envValues = new Map();
    if (!entry.envValues.has(key)) {
      entry.envValues.set(key, readEnvValue(entry.text, key));
    }
    return { exists: true, value: entry.envValues.get(key), error: null };
  }

  getCachedHealth(maxAgeMs = 1500, portOverride) {
    if (!this.lastHealth || !this.lastHealthAt) return null;
    if ((Date.now() - this.lastHealthAt) > maxAgeMs) return null;
    if (portOverride && this.lastHealthPort && portOverride !== this.lastHealthPort) return null;
    return this.lastHealth;
  }

  _clearCachedHealth() {
    this.lastHealth = null;
    this.lastHealthAt = 0;
    this.lastHealthPort = null;
  }

  // ---------------------------------------------------------------------
  // ---------------------------------------------------------------------

  _loadSettings() {
    const defaults = { bind_host: DEFAULT_BIND_HOST };
    try {
      if (!fs.existsSync(this.settingsPath)) return defaults;
      const raw = fs.readFileSync(this.settingsPath, 'utf8');
      const parsed = JSON.parse(raw);
      return { ...defaults, ...parsed };
    } catch (err) {
      console.warn('[settings] could not load, using defaults:', err.message);
      return defaults;
    }
  }

  _saveSettings() {
    try {
      const tmp = this.settingsPath + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(this._settings, null, 2), 'utf8');
      fs.renameSync(tmp, this.settingsPath);
    } catch (err) {
      console.error('[settings] save failed:', err.message);
    }
  }

  getConfigPath() {
    return path.join(this.baseDir, 'config.json');
  }

  readConfigBindHost() {
    try {
      const parsed = this._readCachedJson(this.getConfigPath());
      const prefs = parsed && parsed.server_prefs;
      const host = prefs && prefs.bind_host;
      return (typeof host === 'string' && host.trim()) ? host.trim() : null;
    } catch (err) {
      return null;
    }
  }

  getBindHost() {
    return this.readConfigBindHost()
      || this._settings.bind_host
      || DEFAULT_BIND_HOST;
  }

  getPort() {
    const res = this._readCachedEnvValue('PORT');
    if (!res.exists) {
      if (res.error && res.error.code !== 'ENOENT') {
        throw new Error(`could not read .env to resolve PORT: ${res.error.message}`);
      }
      return DEFAULT_PORT;
    }
    if (res.error) {
      throw new Error(`could not read .env to resolve PORT: ${res.error.message}`);
    }
    const raw = res.value;
    if (raw === null || raw === '') {
      return DEFAULT_PORT;
    }
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
      throw new Error(`PORT in .env is not a valid port number: "${raw}"`);
    }
    return parsed;
  }

  async setBindHost(ip, options = {}) {
    if (!ip || typeof ip !== 'string') {
      throw new Error(`invalid bind host: ${ip}`);
    }
    if (this.getBindHost() === ip) {
      console.log(`[bind-host] already set to ${ip}, no-op`);
      return;
    }
    console.log(`[bind-host] change: ${this._settings.bind_host} -> ${ip}`);
    this._settings.bind_host = ip;
    this._saveSettings();
    await persistBindHost(this.getConfigPath(), ip, options.api);

    await this.restart();
  }

  getLocalInterfaceIps() {
    const now = Date.now();
    if (this._netIfCache && (now - this._netIfCache.at) < NETIF_CACHE_TTL_MS) {
      return this._netIfCache.ips;
    }
    try {
      const ips = listBindableIps();
      this._netIfCache = { at: now, ips };
      return ips;
    } catch (err) {
      console.warn('[bind-host] networkInterfaces() failed:', err.message);
      return [];
    }
  }

  getPrimaryLanIp() {
    const ips = this.getLocalInterfaceIps();
    return ips.length > 0 ? ips[0].ip : null;
  }

  getPublishedUrl() {
    let port;
    try {
      port = this.getPort();
    } catch (err) {
      console.error(`[port] getPublishedUrl: ${err.message}`);
      return null;
    }
    return resolvePublishedUrl({
      port,
      configuredHost: this.getBindHost(),
      measuredHost: this.getEffectiveBindHost(),
      lanIp: this.getPrimaryLanIp(),
    });
  }

  getAppWindowUrl() {
    if (this.startBlockedReason) return null;
    let port;
    try {
      port = this.getPort();
    } catch (err) {
      return null;
    }
    return resolveAppWindowUrl({ port, configuredHost: this.getBindHost(), measuredHost: this.getEffectiveBindHost(), lanIp: this.getPrimaryLanIp() });
  }

  getLocalProbeHost() {
    const h = this.getBindHost();
    return (h === '0.0.0.0' || !h) ? '127.0.0.1' : h;
  }

  probeHostCandidates() {
    const candidates = [this.getLocalProbeHost()];
    if (!candidates.includes('127.0.0.1')) candidates.push('127.0.0.1');
    return candidates;
  }

  getLocalApiUrl() {
    let port;
    try {
      port = this.getPort();
    } catch (err) {
      console.error(`[port] getLocalApiUrl: ${err.message}`);
      return null;
    }
    return `http://${this.getLocalProbeHost()}:${port}`;
  }

  getCurrentOtp() {
    try {
      const res = this._readCachedEnvValue('TOTP_SECRET');
      if (!res.exists || res.error || !res.value) return null;
      return currentTotp(res.value);
    } catch (err) {
      console.warn('[otp] getCurrentOtp failed:', err.message);
      return null;
    }
  }

  findPython() {
    return devProvisioning.findPython({ baseDir: this.baseDir, isPackaged: app.isPackaged });
  }

  async ensureCloudflared() {
    const binDir = path.join(this.baseDir, 'bin');
    const arch = process.arch === 'arm64' ? 'arm64' : 'amd64';

    if (this.payload) {
      try {
        return await ensureVerifiedCloudflared({ binDir, arch, verifyOnly: true });
      } catch (err) {
        console.log(`no verified cloudflared in bin/ (${String(err.message).slice(0, 160)})`);
      }
      const { stdout } = await new Promise((resolve) => exec('which cloudflared', (err, out) => resolve({ stdout: out })));
      if (stdout && stdout.trim()) return 'cloudflared';
      console.log('cloudflared not present; the payload engine does not download it');
      return null;
    }

    if (!fs.existsSync(path.join(binDir, 'cloudflared'))) {
      try {
        const { stdout } = await new Promise((resolve) => exec('which cloudflared', (err, stdout) => resolve({ stdout })));
        if (stdout && stdout.trim()) {
          console.log('cloudflared found in PATH:', stdout.trim());
          return 'cloudflared';
        }
      } catch (e) {
      }
    }

    try {
      const verified = await ensureVerifiedCloudflared({ binDir, arch });
      console.log('cloudflared verified at:', verified);
      return verified;
    } catch (err) {
      console.error('Failed to install cloudflared:', err);
      throw new Error('Failed to install cloudflared: ' + err.message);
    }
  }

  async ensureServerFiles() {
    devProvisioning.ensureServerFiles({ baseDir: this.baseDir, resourcesPath: this.appResourcesPath, isPackaged: app.isPackaged });
  }

  engineBaseEnv(binDir, inherited) {
    if (this.payload) return payloadEngineEnv(this.payload, inherited, binDir, path.join(app.getPath('userData'), 'tmux'));
    const env = { ...inherited };
    env.PATH = `${binDir}:/opt/homebrew/bin:/usr/local/bin:${env.PATH}`;
    return env;
  }

  async ensureVenv() {
    if (this.payload) return;
    const venvPython = await devProvisioning.ensureVenv({ baseDir: this.baseDir, pythonPath: this.pythonPath, exec });
    if (venvPython) this.pythonPath = venvPython;
  }

  async isPortInUse(port = this.getPort()) {
    return new Promise((resolve) => {
      const server = net.createServer();

      server.once('error', (err) => {
        if (err.code === 'EADDRINUSE') {
          resolve(true);
        } else {
          resolve(false);
        }
      });

      server.once('listening', () => {
        server.close();
        resolve(false);
      });

      server.listen(port, '0.0.0.0');
    });
  }

  async start() {
    if (this.startInFlight) { console.log('Server start already in progress'); return; }
    this.startInFlight = true;
    try { await this.startOnce(); } finally { this.startInFlight = false; }
  }

  async startOnce() {
    if (this.process) {
      console.log('Server already running');
      return;
    }

    try {
      await this.ensureServerFiles();
      await this.ensureVenv();
      await this.ensureCloudflared();
    } catch (error) {
      console.error('Setup failed:', error);
      this.state = 'stopped';
      throw error;
    }

    const validation = this.validateEnvFile();
    if (!validation.isValid) {
      const errorMsg = `Configuration validation failed:\n${validation.errors.join('\n')}`;
      console.error(errorMsg);

      const errorLogPath = path.join(app.getPath('userData'), 'logs', 'startup-errors.log');
      try {
        const timestamp = new Date().toISOString();
        appendWithRotation(errorLogPath, `\n[${timestamp}] ${errorMsg}\n`);
        console.log(`Error logged to: ${errorLogPath}`);
      } catch (logErr) {
        console.warn('Could not write to error log:', logErr.message);
      }

      this.state = 'stopped';
      throw new Error(errorMsg);
    }

    const port = this.getPort();
    const portInUse = await require('./engine/port-settle').engineInUse(this, port);
    if (portInUse) {
      console.log(`Port ${port} already in use, checking if it's our server...`);
      const health = this.getCachedHealth(1500, port) || await this.getHealth(port);
      if (health) {
        const holders = await portTrust.listenersStrict(port, { execFile });
        const foreign = portTrust.holderRefusal(holders, process.getuid());
        if (foreign) {
          this.state = 'stopped';
          this.startBlockedReason = `holder-${foreign.reason}`;
          throw portTrust.holderError(foreign, port);
        }
        const bundleVersion = this.getBundleVersion();
        const verdict = decideAdoption({
          runningVersion: health && health.version,
          bundleVersion,
        });
        const holderPid = (holders && holders.length ? holders[0].pid : null) || await this.findPortHolderPid(port);
        this.engineRecord = await engineLifecycle.recordEngine(holderPid, port, verdict.runningVersion);

        if (!verdict.adopt) {
          console.log(
            `Refusing to adopt server on port ${port}: ${verdict.outcome}`
          );
          this.state = 'stopped';
          this.startBlockedReason = verdict.outcome;
          const err = new Error(
            `${verdict.reason}\n\n` +
              `Carnivore did not start this server` +
              (holderPid ? ` (PID ${holderPid})` : '') +
              `, so it will not stop it without being told to.`
          );
          err.code = 'ADOPTION_REFUSED';
          err.outcome = verdict.outcome;
          err.runningVersion = verdict.runningVersion;
          err.bundleVersion = verdict.bundleVersion;
          err.pid = holderPid;
          err.port = port;
          throw err;
        }

        console.log(
          `Adopting server on port ${port}: ${verdict.reason}`
        );
        this.state = 'running';
        this.startTime = Date.now();
        this.ownedProcess = false;
        this.adoptedVersion = verdict.runningVersion;
        this.startBlockedReason = null;
        if (holderPid) {
          console.log(`Adopted existing server process PID: ${holderPid}`);
          this.processPid = holderPid;
        }

        return;
      } else {
        const holder = await this.describePortHolder();
        this.state = 'stopped';
        const refusal = new Error(
          `Port ${port} is already in use by ${holder}, which is not a ` +
            `Carnivore server.\n\n` +
            `Carnivore needs port ${port}. Quit that process, then choose ` +
            `Start Server from the Carnivore menu.`
        );
        refusal.code = 'PORT_HOLDER_NOT_CARNIVORE';
        refusal.port = port;
        throw refusal;
      }
    }

    console.log('Starting Carnivore server...');
    console.log(`Base directory: ${this.baseDir}`);
    console.log(`Python path: ${this.pythonPath}${this.payload ? ' (payload)' : ''}`);
    console.log(`Log file: ${this.logFile}`);

    this.lastExitUnexpected = false;
    this.stopRequested = false;
    this.startBlockedReason = null;
    this._clearCachedHealth();

    const binDir = path.join(this.baseDir, 'bin');
    const env = this.engineBaseEnv(binDir, process.env);

    env.HOST = this.getBindHost();
    console.log(`[spawn] HOST=${env.HOST}`);

    try {
      env.CLOUDE_APP_VERSION = app.getVersion();
      console.log(`[spawn] CLOUDE_APP_VERSION=${env.CLOUDE_APP_VERSION}`);
    } catch (err) {
      console.warn('[spawn] could not resolve app version:', err.message);
    }

    if (app.isPackaged) {
      const bundle = path.resolve(app.getPath('exe'), '..', '..', '..');
      if (bundle.endsWith('.app')) env.CARNIVORE_LAUNCHER_APP = bundle;
    }

    env.CARNIVORE_LOG_FILE = this.logFile;

    const launched = require('./engine-host').getHost().spawnEngine({
      pythonPath: this.pythonPath, cwd: this.baseDir, env, logFile: this.logFile,
      banner: `\n\n=== Server starting at ${new Date().toISOString()} ===\n`,
    });
    this.state = 'starting';
    this.process = launched.child;

    this.processPid = this.process.pid;
    this.ownedProcess = true;
    this.startTime = Date.now();
    console.log(`Server process started with PID: ${this.processPid}`);

    this.attachChildHandlers(this.process);

    console.log('Server process started');
  }

  attachChildHandlers(child) {
    child.on('exit', (code, signal) => {
      if (this.process !== child) return;
      console.log(`Server process exited with code ${code} and signal ${signal}`);
      appendEngineLog(this.logFile, `\n=== Server stopped at ${new Date().toISOString()} (code: ${code}, signal: ${signal}) ===\n`);

      this.lastExit = { code, signal, at: Date.now() };
      this.lastExitUnexpected = !this.stopRequested;
      const wasExpected = this.stopRequested;
      this.stopRequested = false;

      this.process = null;
      this.processPid = null;
      this.ownedProcess = false;
      this.state = 'stopped';
      this.startTime = null;

      this.superviseDown({ expected: wasExpected });
    });

    child.on('error', (err) => {
      if (this.process !== child) return;
      console.error('Failed to start server:', err);
      appendEngineLog(this.logFile, `\n=== Server error: ${err.message} ===\n`);

      this.lastExit = { code: null, signal: null, error: err.message, at: Date.now() };
      this.lastExitUnexpected = true;
      this.stopRequested = false;

      this.process = null;
      this.processPid = null;
      this.ownedProcess = false;
      this.state = 'stopped';
      this.startTime = null;
    });
  }

  /* could not be determined */
  getBundleVersion() {
    try {
      return app.getVersion() || '';
    } catch (err) {
      console.warn('Could not resolve this bundle version:', err.message);
      return '';
    }
  }

  findPortHolderPid(port) {
    return portTrust.listeners(port, { execFile }).then((found) => (found && found.length ? found[0].pid : null));
  }

  superviseDown(event = {}) {
    const decision = this.supervisor.recordDown({
      expected: event.expected === true,
      quitting: this.quitting === true,
    });
    console.log(`[supervisor] ${decision.message}`);

    this.slowRetry.onGaveUp(decision, event.startError);
    if (decision.action !== SUPERVISOR_RESTART) return decision;

    if (this.supervisorTimer) clearTimeout(this.supervisorTimer);
    this.supervisorTimer = setTimeout(async () => {
      this.supervisorTimer = null;
      if (this.quitting) return;
      try {
        await this.start();
        this.supervisor.recordUp();
      } catch (err) {
        console.error(`[supervisor] restart failed: ${err.message}`);
        this.superviseDown({ expected: false, startError: err });
      }
    }, decision.delayMs);

    return decision;
  }

  healthDown() { return (this.healthMisses || 0) >= DOWN_AFTER_MISSES; }

  superviseTick(healthy) {
    this.healthMisses = healthy ? 0 : (this.healthMisses || 0) + 1;
    if (this.quitting || this.stopRequested) return;
    if (healthy) {
      this.supervisor.noteStillUp();
      return;
    }
    if (!this.healthDown()) return;
    if (this.state !== 'running' || (this.startBlockedReason && this.startBlockedReason !== this.startBlockedByGuard)) return;
    this.state = 'stopped';
    if (!this.ownedProcess && this.serviceOwnsEngine()) { this.awaitingService = true; console.log('[supervisor] the login service owns the engine: not restarting it; watching for it to come back'); return; }
    this.superviseDown({ expected: false });
  }

  resetSupervisor() { this.slowRetry.cancel();
    if (this.supervisorTimer) {
      clearTimeout(this.supervisorTimer);
      this.supervisorTimer = null;
    }
    this.supervisor.reset();
  }

  getSupervisorStatus() {
    return {
      ...this.supervisor.status(),
      pending: this.supervisorTimer !== null,
      slowRetry: this.slowRetry.pending(),
    };
  }

  cancelSlowRetry() { this.slowRetry.cancel(); }

  /* cannot be undone */
  beginQuit() {
    this.quitting = true; this.slowRetry.cancel();
    if (this.supervisorTimer) {
      clearTimeout(this.supervisorTimer);
      this.supervisorTimer = null;
    }
  }

  cancelQuit() { this.quitting = false; }

  async engineIsUp(port = this.getPort()) {
    return Boolean(await this.getHealth(port)) || (await this.isPortInUse(port));
  }

  stopEngine(options = {}) {
    return engineLifecycle.stopEngine(this, options);
  }

  restartAdoptedEngine(options = {}) {
    return engineLifecycle.restartAdoptedEngine(this, options);
  }

  async waitForPortFree(port, budgetMs = 5000, pollMs = 75) {
    const deadline = Date.now() + budgetMs;
    for (;;) {
      if (!(await this.isPortInUse(port))) return true;
      if (Date.now() >= deadline) return false;
      await new Promise((resolve) => setTimeout(resolve, pollMs));
    }
  }

  /* this app did not start */
  async takeOverPort() {
    const port = this.getPort();
    const pid = await this.findPortHolderPid(port);
    if (!pid) {
      throw new Error(
        `Could not determine which process is holding port ${port}, so ` +
          `Carnivore will not try to stop it. Quit it yourself and choose ` +
          `Start Server.`
      );
    }

    console.log(`Taking over port ${port} from PID ${pid} (user approved)...`);
    const result = await terminateProcess(pid, { graceMs: 5000 });
    if (!result.terminated) {
      throw new Error(
        `Could not stop the process on port ${port} (PID ${pid}): ` +
          `${result.outcome}. Nothing was started.`
      );
    }

    if (!(await this.waitForPortFree(port))) {
      throw new Error(
        `PID ${pid} exited but port ${port} is still held. Nothing was ` +
          `started - something else may have taken the port.`
      );
    }

    this.startBlockedReason = null;
    this.adoptedVersion = null;
    await this.start();
  }

  describePortHolder() {
    let port;
    try {
      port = this.getPort();
    } catch (err) {
      return Promise.resolve('another process');
    }
    return this.findPortHolderPid(port).then((pid) => {
      if (pid === null) return 'another process';
      return new Promise((resolve) => {
        exec(`ps -p ${pid} -o comm=`, (psErr, psOut) => {
          const name = String(psOut || '').trim();
          const base = name ? name.split('/').pop() : '';
          resolve(base ? `PID ${pid} (${base})` : `PID ${pid}`);
        });
      });
    });
  }

  async stop(options = {}) {
    console.log('Stopping server...');

    const verdict = decideLifecycleAction({
      action: 'stop',
      owned: this.ownedProcess,
      takeOwnership: options.takeOwnership === true,
      serverResponding: this.processPid ? isAlive(this.processPid) : null,
    });

    if (!verdict.permitted) {
      console.log(this.state === 'stopped'
        ? 'Not stopping: this app holds no server of its own, nothing to stop.'
        : `Refusing to stop: ${verdict.reason}`);
      if (verdict.stateAfterRefusal) {
        this.state = verdict.stateAfterRefusal;
      }
      return {
        stopped: false,
        refused: true,
        reason: verdict.reason,
        offerTakeOwnership: verdict.offerTakeOwnership,
        pid: this.processPid,
      };
    }

    this.stopRequested = true; this.slowRetry.cancel();
    this.lastExitUnexpected = false;

    const pid = this.processPid || (this.process && this.process.pid) || null;
    let outcome = 'no-pid';
    if (pid) {
      console.log(`Terminating owned server PID ${pid}...`);
      const result = await terminateProcess(pid, { graceMs: 3000 });
      outcome = result.outcome;
      if (result.escalated) {
        console.log(`PID ${pid} ignored SIGTERM; escalated to SIGKILL`);
      }
      if (!result.terminated) {
        console.error(
          `Could not confirm PID ${pid} exited (${result.outcome}). ` +
          `The port may still be held.`
        );
      }
    }

    if (pid && isAlive(pid)) {
      const waitDeadline = Date.now() + 500;
      while (isAlive(pid) && Date.now() < waitDeadline) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    }

    if (pid && isAlive(pid)) {
      console.error(`PID ${pid} is still alive after stop(); not reporting stopped.`);
      return { stopped: false, outcome, pid };
    }

    this._clearCachedHealth();
    this.process = null;
    this.processPid = null;
    this.ownedProcess = false;
    this.state = 'stopped';
    this.startTime = null;
    return { stopped: true, outcome, pid };
  }

  async restart(options = {}) {
    console.log('Restarting server...');

    const verdict = decideLifecycleAction({
      action: 'restart',
      owned: this.ownedProcess,
      takeOwnership: options.takeOwnership === true,
      serverResponding: this.processPid ? isAlive(this.processPid) : null,
    });

    if (!verdict.permitted) {
      console.log(`Refusing to restart: ${verdict.reason}`);
      if (verdict.stateAfterRefusal) {
        this.state = verdict.stateAfterRefusal;
      }
      return {
        restarted: false,
        refused: true,
        reason: verdict.reason,
        offerTakeOwnership: verdict.offerTakeOwnership,
        pid: this.processPid,
      };
    }

    if (!this.ownedProcess && options.takeOwnership === true) {
      await this.takeOverPort();
      console.log('Server restarted under new ownership');
      return { restarted: true, refused: false, tookOwnership: true };
    }

    const stopResult = await this.stop();
    if (stopResult && stopResult.stopped === false) {
      console.error(`Not restarting: stop() did not confirm the exit (${stopResult.outcome || stopResult.reason || 'unknown'}).`);
      return { restarted: false, refused: false, stopFailed: true, reason: stopResult.reason || stopResult.outcome, pid: stopResult.pid };
    }

    let port = null;
    try {
      port = this.getPort();
    } catch (_) {
      port = null;
    }
    if (port !== null) {
      await this.waitForPortFree(port, 5000, 75);
    }

    await this.start();
    console.log('Server restarted');
    return { restarted: true, refused: false, tookOwnership: false };
  }

  async getHealth(portOverride, options = {}) {
    let port;
    try {
      port = portOverride || this.getPort();
    } catch (err) {
      console.error(`[port] getHealth: ${err.message}`);
      return null;
    }

    if (!options.fresh) {
      const cached = this.getCachedHealth(HEALTH_COALESCE_MS, port);
      if (cached) return cached;
    }
    if (!this._healthInFlight) this._healthInFlight = new Map();
    const existing = this._healthInFlight.get(port);
    if (existing) return existing;

    const promise = this._probeHealth(port).finally(() => {
      if (this._healthInFlight.get(port) === promise) this._healthInFlight.delete(port);
    });
    this._healthInFlight.set(port, promise);
    return promise;
  }

  async _probeHealth(port) {
    for (const host of this.probeHostCandidates()) {
      const base = `http://${host}:${port}`;
      let stats;
      try {
        stats = await httpGetJson(`${base}/api/v1/health`, 3000);
      } catch (err) {
        continue;
      }

      this.lastHealth = stats;
      this.lastHealthAt = Date.now();
      this.lastHealthPort = port;

      this.healthProbeCount = (this.healthProbeCount || 0) + 1;
      const exposureKnown = this.reportedBind && this.reportedSetupStatus === 'complete';
      if (exposureKnown && this.healthProbeCount % EXPOSURE_REFRESH_EVERY !== 0) {
        return stats;
      }
      try {
        const exposureData = await httpGetJson(`${base}/health`, 3000);
        const bind = exposureData && exposureData.bind;
        this.reportedBind = bind || null;
        this.reportedSetupStatus =
          (exposureData && exposureData.setup_status) || null;
        this.reportedJoined = exposureData && typeof exposureData.joined === 'boolean'
          ? exposureData.joined : null;
        this.reportedRebindRequested = Boolean(exposureData && exposureData.rebind_requested);
        this.reportedDoorFile = exposureData && typeof exposureData.door_file === 'string'
          ? exposureData.door_file : null;
      } catch (err) {
        // could not be read
        this.reportedBind = null;
        this.reportedSetupStatus = null;
        this.reportedJoined = null;
        this.reportedRebindRequested = false;
        this.reportedDoorFile = null;
      }
      return stats;
    }
    this._clearCachedHealth();
    this.healthProbeCount = 0;
    this.reportedBind = null;
    this.reportedSetupStatus = null;
    this.reportedJoined = null;
    this.reportedRebindRequested = false;
    return null;
  }

  /* could not be determined the bind was not measured */
  getMeasuredUrl() {
    const host = this.getEffectiveBindHost();
    if (!host) return null;
    let port;
    try {
      port = this.getPort();
    } catch (err) {
      console.error(`[port] getMeasuredUrl: ${err.message}`);
      return null;
    }
    if (host === '0.0.0.0') {
      const lan = this.getPrimaryLanIp();
      return `http://${lan || '127.0.0.1'}:${port}`;
    }
    return `http://${host}:${port}`;
  }

  getEffectiveBindHost() {
    return (this.reportedBind && this.reportedBind.effective_host) || null;
  }

  isBindLockedDown() {
    if (!this.reportedBind) return null;
    return Boolean(this.reportedBind.locked_down);
  }

  getSetupStatus() {
    return this.reportedSetupStatus;
  }

  getBindReport() {
    const bind = this.reportedBind ? { ...this.reportedBind } : null;
    return {
      setup_status: this.reportedSetupStatus,
      bind,
      joined: this.reportedJoined === undefined ? null : this.reportedJoined,
      rebind_requested: this.reportedRebindRequested === true,
      door_file: this.reportedDoorFile || null,
    };
  }

  getUptime() {
    if (!this.startTime) return 0;
    return Math.floor((Date.now() - this.startTime) / 1000);
  }

  getState() {
    return this.state;
  }

  isProcessRunning() {
    const pid = this.processPid || (this.process && this.process.pid) || null;
    if (!pid) return false;
    if (isAlive(pid)) return true;
    this.processPid = null;
    return false;
  }

  validateEnvFile() {
    return validateEnvFile(this.baseDir, () => this.getPort());
  }

  getSetupVerdict() {
    const facts = this.readSetupFacts();
    let local;
    if (
      this._localSetupCache
      && this._localSetupCache.envText === facts.envText
      && this._localSetupCache.configText === facts.configText
      && this._localSetupCache.pairedExists === facts.pairedExists
    ) {
      local = this._localSetupCache.local;
    } else {
      local = setupVerdict.evaluateLocalSetup(facts);
      this._localSetupCache = {
        envText: facts.envText,
        configText: facts.configText,
        pairedExists: facts.pairedExists,
        local,
      };
    }
    const resolved = setupVerdict.resolveSetupVerdict({
      serverStatus: this.getSetupStatus(),
      local,
    });
    return { ...resolved, checks: local.checks };
  }

  readSetupFacts() {
    const envEntry = this._readCachedFile(path.join(this.baseDir, '.env'));
    const cfgEntry = this._readCachedFile(this.getConfigPath());

    let pairedExists;
    try {
      pairedExists = fs.existsSync(path.join(this.baseDir, '.totp_paired'));
    } catch (err) {
      pairedExists = null;
    }

    return {
      envText: envEntry.exists ? envEntry.text : null,
      configText: cfgEntry.exists ? cfgEntry.text : null,
      pairedExists,
    };
  }

  getProjectRoot() {
    return this.baseDir;
  }
}

module.exports = ServerManager;
