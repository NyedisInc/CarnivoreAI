const { exec, execFile } = require('child_process');
const portTrust = require('./tray-menu/port-trust');
const path = require('path');
const { persistBindHost } = require('./bind-settings');
const axios = require('axios');
const { app } = require('electron');
const net = require('net');
const fs = require('fs');
const os = require('os');
const { currentTotp, secondsUntilRollover } = require('./totp');
const { readEnvValue, validateEnvFile } = require('./env-file');
const devProvisioning = require('./dev-provisioning');
const { terminateProcess, isAlive } = require('./process-teardown');
const { decideAdoption } = require('./adoption-decision');
const { decideLifecycleAction } = require('./ownership-policy');
const EXPOSURE_REFRESH_EVERY = 4;
const { createSupervisor, SUPERVISOR_RESTART } = require('./supervisor-policy');
const { createSlowRetry } = require('./supervisor-slow-retry');
const setupVerdict = require('./setup-verdict');
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
      const raw = fs.readFileSync(this.getConfigPath(), 'utf8');
      const parsed = JSON.parse(raw);
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
    const envPath = path.join(this.baseDir, '.env');
    if (!fs.existsSync(envPath)) {
      return DEFAULT_PORT;
    }
    let envText;
    try {
      envText = fs.readFileSync(envPath, 'utf8');
    } catch (err) {
      throw new Error(`could not read .env to resolve PORT: ${err.message}`);
    }
    const raw = readEnvValue(envText, 'PORT');
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
    try {
      return listBindableIps();
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
      const envPath = path.join(this.baseDir, '.env');
      if (!fs.existsSync(envPath)) return null;
      const envText = fs.readFileSync(envPath, 'utf8');
      const secret = readEnvValue(envText, 'TOTP_SECRET');
      if (!secret) return null;
      return currentTotp(secret);
    } catch (err) {
      console.warn('[otp] getCurrentOtp failed:', err.message);
      return null;
    }
  }

  getOtpSecondsRemaining() {
    return secondsUntilRollover();
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
      const health = await this.getHealth();
      if (health) {
        const foreign = portTrust.holderRefusal(await portTrust.listeners(port, { execFile }), process.getuid());
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
        const holderPid = await this.findPortHolderPid(port);
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
    return new Promise((resolve) => {
      exec(`lsof -nP -iTCP:${port} -sTCP:LISTEN -t`, (err, stdout) => {
        if (err) {
          resolve(null);
          return;
        }
        const first = String(stdout || '').trim().split('\n')[0];
        const pid = parseInt(first, 10);
        resolve(Number.isNaN(pid) ? null : pid);
      });
    });
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

  superviseTick(healthy) {
    if (this.quitting || this.stopRequested) return;
    if (healthy) {
      this.supervisor.noteStillUp();
      return;
    }
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

  async waitForPortFree(port, budgetMs = 5000, pollMs = 150) {
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

    await new Promise(resolve => setTimeout(resolve, 500));

    if (pid && isAlive(pid)) {
      console.error(`PID ${pid} is still alive after stop(); not reporting stopped.`);
      return { stopped: false, outcome, pid };
    }

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

    await new Promise(resolve => setTimeout(resolve, 3000));

    await this.start();
    console.log('Server restarted');
    return { restarted: true, refused: false, tookOwnership: false };
  }

  async getHealth(portOverride) {
    let port;
    try {
      port = portOverride || this.getPort();
    } catch (err) {
      console.error(`[port] getHealth: ${err.message}`);
      return null;
    }

    for (const host of this.probeHostCandidates()) {
      const base = `http://${host}:${port}`;
      let stats;
      try {
        const response = await axios.get(`${base}/api/v1/health`, { timeout: 3000 });
        stats = response.data;
      } catch (err) {
        continue;
      }

      this.healthProbeCount = (this.healthProbeCount || 0) + 1;
      const exposureKnown = this.reportedBind && this.reportedSetupStatus === 'complete';
      if (exposureKnown && this.healthProbeCount % EXPOSURE_REFRESH_EVERY !== 0) {
        return stats;
      }
      try {
        const exposure = await axios.get(`${base}/health`, { timeout: 3000 });
        const bind = exposure.data && exposure.data.bind;
        this.reportedBind = bind || null;
        this.reportedSetupStatus =
          (exposure.data && exposure.data.setup_status) || null;
        this.reportedJoined = exposure.data && typeof exposure.data.joined === 'boolean'
          ? exposure.data.joined : null;
        this.reportedRebindRequested = Boolean(exposure.data && exposure.data.rebind_requested);
        this.reportedDoorFile = exposure.data && typeof exposure.data.door_file === 'string'
          ? exposure.data.door_file : null;
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
    const local = setupVerdict.evaluateLocalSetup(this.readSetupFacts());
    const resolved = setupVerdict.resolveSetupVerdict({
      serverStatus: this.getSetupStatus(),
      local,
    });
    return { ...resolved, checks: local.checks };
  }

  readSetupFacts() {
    const read = (file) => {
      try {
        return fs.readFileSync(path.join(this.baseDir, file), 'utf8');
      } catch (err) {
        return null;
      }
    };

    let pairedExists;
    try {
      pairedExists = fs.existsSync(path.join(this.baseDir, '.totp_paired'));
    } catch (err) {
      pairedExists = null;
    }

    return {
      envText: read('.env'),
      configText: read('config.json'),
      pairedExists,
    };
  }

  getProjectRoot() {
    return this.baseDir;
  }
}

module.exports = ServerManager;
