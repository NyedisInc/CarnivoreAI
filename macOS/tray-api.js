// WHY THIS FILE EXISTS

'use strict';

const TOKEN_REFRESH_MARGIN_SECONDS = 300;

const REQUEST_TIMEOUT_MS = 8000;

const TRAY_LISTING_MAX_AGE_S = 30;

function listRowsFromBody(body) {
  if (Array.isArray(body)) return body;
  const list = body && body.collections && body.collections.list;
  if (!list || list.ok !== true || !Array.isArray(list.rows)) return null;
  return list.rows;
}

const STALE_SOCKET_CODES = new Set(['ECONNRESET', 'EPIPE', 'UND_ERR_SOCKET']);

class TrayApiClient {
  constructor(options) {
    this.baseUrl = String(options.baseUrl || '').replace(/\/+$/, '');
    this.getOtp = options.getOtp;
    this.fetchImpl = options.fetchImpl || global.fetch;
    this.now = options.now || (() => Date.now());
    this.isJoined = options.isJoined || (() => false);
    this.localLogin = options.localLogin || null;

    this.accessToken = null;
    this.accessTokenExpiresAt = 0;
    this.refreshToken = null;
    this.tokenFlight = null;
  }

  setBaseUrl(baseUrl) {
    const next = String(baseUrl || '').replace(/\/+$/, '');
    if (next === this.baseUrl) return;
    this.baseUrl = next;
    this.forgetToken();
  }

  forgetToken() {
    this.accessToken = null;
    this.accessTokenExpiresAt = 0;
    this.refreshToken = null;
  }

  async request(routePath, options) {
    const first = await this._requestOnce(routePath, options);
    return first.staleSocket ? this._requestOnce(routePath, options) : first;
  }

  async _requestOnce(routePath, options) {
    const opts = options || {};
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const headers = { Accept: 'application/json' };
      if (opts.body) headers['Content-Type'] = 'application/json';
      if (opts.token) headers.Authorization = `Bearer ${opts.token}`;

      const response = await this.fetchImpl(this.baseUrl + routePath, {
        method: opts.method || 'GET',
        headers,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      });

      let data = null;
      try {
        data = await response.json();
      } catch (parseError) {
        data = null;
      }

      return {
        ok: response.ok,
        status: response.status,
        data,
        error: response.ok ? null : `HTTP ${response.status}`,
      };
    } catch (transportError) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: String((transportError && transportError.message) || transportError),
        staleSocket: STALE_SOCKET_CODES.has(transportError && transportError.cause && transportError.cause.code),
      };
    } finally {
      clearTimeout(timer);
    }
  }

  _adoptTokens(data) {
    if (!data || !data.access_token) return false;
    this.accessToken = data.access_token;
    const ttl = Number(data.expires_in) || 0;
    this.accessTokenExpiresAt = this.now() + Math.max(0, ttl) * 1000;
    if (data.refresh_token) this.refreshToken = data.refresh_token;
    return true;
  }

  ensureToken() {
    if (this.tokenFlight) return this.tokenFlight;
    const flight = this._mintToken().finally(() => {
      if (this.tokenFlight === flight) this.tokenFlight = null;
    });
    this.tokenFlight = flight;
    return flight;
  }

  async _mintToken() {
    const marginMs = TOKEN_REFRESH_MARGIN_SECONDS * 1000;
    if (this.accessToken && this.now() + marginMs < this.accessTokenExpiresAt) {
      return { token: this.accessToken, error: null };
    }

    if (this.refreshToken) {
      const refreshed = await this.request('/api/v1/auth/refresh', {
        method: 'POST',
        body: { refresh_token: this.refreshToken },
      });
      if (refreshed.ok && this._adoptTokens(refreshed.data)) {
        return { token: this.accessToken, error: null };
      }
      this.refreshToken = null;
    }

    if (this.localLogin && this.isJoined() === true) {
      const tokens = await this.localLogin();
      if (tokens && this._adoptTokens(tokens)) {
        return { token: this.accessToken, error: null };
      }
      return { token: null, error: 'the local login was refused' };
    }

    let code = null;
    try {
      code = this.getOtp ? this.getOtp() : null;
    } catch (otpError) {
      return { token: null, error: 'could not compute a TOTP code' };
    }
    if (!code) return { token: null, error: 'no TOTP secret available' };

    const verified = await this.request('/api/v1/auth/verify', {
      method: 'POST',
      body: { code },
    });
    if (verified.ok && this._adoptTokens(verified.data)) {
      return { token: this.accessToken, error: null };
    }

    return {
      token: null,
      error: verified.error || 'TOTP verification was rejected',
    };
  }

  async getAuthed(routePath) {
    const first = await this.ensureToken();
    if (!first.token) return { reachable: false, data: null, error: first.error };

    let response = await this.request(routePath, { token: first.token });
    if (response.status === 401) {
      this.forgetToken();
      const second = await this.ensureToken();
      if (!second.token) {
        return { reachable: false, data: null, error: second.error };
      }
      response = await this.request(routePath, { token: second.token });
    }

    if (!response.ok) {
      return { reachable: false, status: response.status, data: null, error: response.error };
    }
    return { reachable: true, status: response.status, data: response.data, error: null };
  }

  async sendAuthed(routePath, body, method) {
    const verb = method || 'PUT';
    const first = await this.ensureToken();
    if (!first.token) return { reachable: false, data: null, error: first.error };

    let response = await this.request(routePath, { method: verb, body, token: first.token });
    if (response.status === 401) {
      this.forgetToken();
      const second = await this.ensureToken();
      if (!second.token) {
        return { reachable: false, data: null, error: second.error };
      }
      response = await this.request(routePath, { method: verb, body, token: second.token });
    }

    if (!response.ok) {
      return { reachable: false, status: response.status, data: null, body: response.data, error: response.error };
    }
    return { reachable: true, status: response.status, data: response.data, error: null };
  }

  async fetchSessions() {
    const pushed = await this.getAuthed(
      `/api/v1/sessions/listing?max_age=${TRAY_LISTING_MAX_AGE_S}`
    );
    const rows = pushed.reachable ? listRowsFromBody(pushed.data) : null;
    if (rows) return { reachable: true, sessions: rows, error: null };

    const result = await this.getAuthed('/api/v1/sessions/list');
    if (!result.reachable) {
      return { reachable: false, sessions: null, error: result.error };
    }
    return {
      reachable: true,
      sessions: Array.isArray(result.data) ? result.data : [],
      error: null,
    };
  }
}

module.exports = { TrayApiClient, TOKEN_REFRESH_MARGIN_SECONDS };
