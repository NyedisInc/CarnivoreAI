
import { t } from '../../lib/i18n/index.svelte';

const ACCESS_KEY = 'claude_tunnel_token';

const REFRESH_KEY = 'claude_refresh_token';

const BASE = '/api/v1';

export const API_BASE = BASE;

export type AuthState = 'unknown' | 'signed-in' | 'signed-out' | 'unreachable';

function read(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function decideBootState(hasAccess: boolean, hasRefresh: boolean): AuthState {
  void hasRefresh;
  return hasAccess ? 'signed-in' : 'signed-out';
}

export const auth = $state<{ state: AuthState; notice: string }>({
  state: decideBootState(Boolean(read(ACCESS_KEY)), Boolean(read(REFRESH_KEY))),
  notice: '',
});

export const API_REFUSAL_EVENT = 'cloude:api-refusal';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(
    message: string,
    status: number,
    code: string | null = null,
    payload: unknown = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

function write(key: string, value: string | null): void {
  try {
    const store = globalThis.localStorage;
    if (!store) return;
    if (value === null) store.removeItem(key);
    else store.setItem(key, value);
  } catch {
  }
}

export function hasAccessToken(): boolean {
  return Boolean(read(ACCESS_KEY));
}

export function hasRefreshToken(): boolean {
  return Boolean(read(REFRESH_KEY));
}

export function accessToken(): string | null {
  return read(ACCESS_KEY);
}

function clearTokens(): void {
  write(ACCESS_KEY, null);
  write(REFRESH_KEY, null);
}

export function initAuth(): void {
  auth.state = decideBootState(hasAccessToken(), hasRefreshToken());
  auth.notice = '';
}

function detailOf(body: unknown): string {
  if (!body || typeof body !== 'object') return '';
  const record = body as Record<string, unknown>;
  const detail = record['detail'];
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const inner = detail as Record<string, unknown>;
    if (typeof inner['message'] === 'string' && inner['message']) return inner['message'] as string;
    if (typeof inner['detail'] === 'string' && inner['detail']) return inner['detail'] as string;
    if (typeof inner['reason'] === 'string' && inner['reason']) {
      return (inner['reason'] as string) === 'code_reused'
        ? t('opscenter.auth.code_reused')
        : (inner['reason'] as string);
    }
  }
  if (typeof record['message'] === 'string' && record['message']) return record['message'] as string;
  return '';
}

export function errorCodeOf(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  if (typeof record['code'] === 'string' && record['code']) return record['code'];
  const detail = record['detail'];
  if (detail && typeof detail === 'object') {
    const inner = (detail as Record<string, unknown>)['code'];
    if (typeof inner === 'string' && inner) return inner;
  }
  return null;
}

export function codedSentence(body: unknown, fallback: string): string {
  const code = errorCodeOf(body);
  if (!code) return fallback;
  const key = `api.error.${code}`;
  const sentence = t(key);
  return sentence && sentence !== key ? sentence : fallback;
}

let refreshInFlight: Promise<boolean> | null = null;

const REFRESH_LOCK = 'carnivore-auth-refresh';

const LOCK_WAIT_MS = 20000;

async function withRefreshLock(work: () => Promise<boolean>): Promise<boolean> {
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (!locks || typeof locks.request !== 'function') return work();
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), LOCK_WAIT_MS);
  try {
    return await locks.request(REFRESH_LOCK, { signal: abort.signal }, async () => {
      clearTimeout(timer);
      return work();
    });
  } catch (error) {
    if ((error as { name?: string })?.name === 'AbortError') return false;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export function refreshTokens(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  const stored = read(REFRESH_KEY);
  if (!stored) {
    clearTokens();
    auth.state = 'signed-out';
    return Promise.resolve(false);
  }
  refreshInFlight = withRefreshLock(() => rotate(stored)).finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function rotate(stored: string): Promise<boolean> {
  const current = read(REFRESH_KEY);
  if (current !== stored) {
    if (current && read(ACCESS_KEY)) {
      auth.state = 'signed-in';
      auth.notice = '';
      return true;
    }
    auth.state = 'signed-out';
    return false;
  }
  let response: Response;
  try {
    response = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: stored }),
    });
  } catch {
    auth.state = 'unreachable';
    auth.notice = t('opscenter.app.backend_unreachable');
    return false;
  }
  if (response.status >= 500 || response.status === 408 || response.status === 429) {
    write(ACCESS_KEY, null);
    auth.state = 'unreachable';
    auth.notice = t('opscenter.app.backend_unreachable');
    return false;
  }
  if (!response.ok) {
    clearTokens();
    auth.state = 'signed-out';
    auth.notice = '';
    return false;
  }
  const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  const access = typeof body?.['access_token'] === 'string'
    ? (body['access_token'] as string)
    : typeof body?.['token'] === 'string' ? (body['token'] as string) : '';
  if (!access) {
    clearTokens();
    auth.state = 'signed-out';
    return false;
  }
  write(ACCESS_KEY, access);
  if (typeof body?.['refresh_token'] === 'string' && body['refresh_token']) {
    write(REFRESH_KEY, body['refresh_token'] as string);
  }
  auth.state = 'signed-in';
  auth.notice = '';
  return true;
}

export function authFetch<T>(
  path: string,
  init: RequestInit = {},
  retrying = false,
): Promise<T> {
  const dedupe = retrying ? undefined : (globalThis as { BootFetchDedupe?: BootFetchDedupe }).BootFetchDedupe;
  if (!dedupe) return request(path, init, retrying, readBody<T>);
  return dedupe.run(`web:${BASE}${path}`, init, () => request(path, init, retrying, readBody<T>)) as Promise<T>;
}

interface BootFetchDedupe {
  run(key: string, init: RequestInit, start: () => Promise<unknown>): Promise<unknown>;
}

export function authFetchBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  return request(path, init, false, (response) => response.blob());
}

async function readBody<T>(response: Response): Promise<T> {
  // there is nothing
  if (response.status === 204) {
    await response.arrayBuffer().catch(() => undefined);
    return undefined as T;
  }
  const kind = response.headers?.get?.('content-type') ?? '';
  if (kind.startsWith('application/zip') || (response.headers?.get?.('content-disposition') && !kind.includes('json'))) {
    const blob = await response.blob();
    const name = /filename="?([^";/\\]+)"?/i.exec(response.headers.get('content-disposition') ?? '')?.[1];
    return (name ? new File([blob], name, { type: blob.type }) : blob) as T;
  }
  return (await response.json()) as T;
}

async function request<T>(
  path: string,
  init: RequestInit,
  retrying: boolean,
  answer: (response: Response) => Promise<T>,
): Promise<T> {
  const token = read(ACCESS_KEY);
  const headers = new Headers(init.headers ?? {});
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    auth.state = 'unreachable';
    auth.notice = t('opscenter.app.backend_unreachable');
    throw new ApiError(t('opscenter.app.backend_unreachable'), 0, 'unreachable');
  }

  if (response.status === 401) {
    if (!retrying && hasRefreshToken()) {
      const rotated = await refreshTokens();
      if (rotated) return request(path, init, true, answer);
      throw new ApiError(t('opscenter.auth.sign_in_again'), 401, 'signed-out');
    }
    clearTokens();
    auth.state = 'signed-out';
    auth.notice = '';
    throw new ApiError(t('opscenter.auth.sign_in_again'), 401, 'signed-out');
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as unknown;
    const message = codedSentence(
      body,
      detailOf(body) || t('opscenter.auth.server_answered', { status: response.status }),
    );
    const code = errorCodeOf(body);
    globalThis.dispatchEvent?.(new CustomEvent(API_REFUSAL_EVENT, { detail: { status: response.status, body } }));
    throw new ApiError(message, response.status, code, body);
  }

  if (auth.state !== 'signed-in') {
    auth.state = 'signed-in';
    auth.notice = '';
  }
  return answer(response);
}

export async function signIn(code: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
  } catch {
    auth.state = 'unreachable';
    auth.notice = t('opscenter.app.backend_unreachable');
    throw new ApiError(t('opscenter.app.backend_unreachable'), 0, 'unreachable');
  }
  const body = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  if (!response.ok) {
    throw new ApiError(
      detailOf(body) || t('opscenter.auth.server_answered', { status: response.status }),
      response.status,
    );
  }
  const access = typeof body?.['access_token'] === 'string'
    ? (body['access_token'] as string)
    : typeof body?.['token'] === 'string' ? (body['token'] as string) : '';
  if (!access) throw new ApiError(t('opscenter.auth.no_token'), response.status);
  write(ACCESS_KEY, access);
  if (typeof body?.['refresh_token'] === 'string' && body['refresh_token']) {
    write(REFRESH_KEY, body['refresh_token'] as string);
  }
  auth.state = 'signed-in';
  auth.notice = '';
}

export function signOut(): void {
  const stored = read(REFRESH_KEY);
  if (stored) {
    void fetch(`${BASE}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: stored }),
    }).catch(() => {
    });
  }
  clearTokens();
  auth.state = 'signed-out';
  auth.notice = '';
}
