
import { subscribe } from '../../opscenter/api/events.svelte';
import { authFetch } from '../../opscenter/api/auth.svelte';
import type { EventFrame } from '../../opscenter/api/types';
import { resourcePush } from '../resource-push/boot';

const META_NAME = 'cloude-app-version';

const BUILD_META_NAME = 'cloude-client-build';

export const CLIENT_BUILD_POLL_MS = 60_000;

function readMeta(name: string): string {
  try {
    const meta = document.querySelector(`meta[name="${name}"]`);
    return meta ? (meta.getAttribute('content') || '').trim() : '';
  } catch {
    return '';
  }
}

function readPageVersion(): string {
  return readMeta(META_NAME);
}

export interface VersionWatchState {
  pageVersion: string;
  latestServerVersion: string;
  dismissedVersion: string;
  pageClientBuild: string;
  latestClientBuild: string;
  dismissedClientBuild: string;
}

export type BannerKind = 'version' | 'client' | null;

export const versionWatch: VersionWatchState = $state({
  pageVersion: readPageVersion(),
  latestServerVersion: '',
  dismissedVersion: '',
  pageClientBuild: readMeta(BUILD_META_NAME),
  latestClientBuild: '',
  dismissedClientBuild: '',
});

export function normalizeVersion(value: string): string {
  return value.trim().replace(/^[vV]+/, '').trim();
}

export function computeShowBanner(state: VersionWatchState): boolean {
  return bannerKind(state) !== null;
}

export function bannerKind(state: VersionWatchState): BannerKind {
  const page = normalizeVersion(state.pageVersion);
  const server = normalizeVersion(state.latestServerVersion);
  if (
    page !== '' &&
    server !== '' &&
    server !== page &&
    normalizeVersion(state.dismissedVersion) !== server
  ) {
    return 'version';
  }
  const build = state.latestClientBuild.trim();
  if (
    state.pageClientBuild.trim() !== '' &&
    build !== '' &&
    build !== state.pageClientBuild.trim() &&
    state.dismissedClientBuild.trim() !== build
  ) {
    return 'client';
  }
  return null;
}

export interface WhatsNewEntry {
  type: string;
  summary: string;
  feature: string;
  where: string[];
  how_to: string[];
}

export const whatsNew: { mark: string; entries: WhatsNewEntry[]; more: number } = $state({
  mark: '',
  entries: [],
  more: 0,
});

interface WhatsNewResponse {
  mark?: string;
  more?: number;
  entries?: WhatsNewEntry[];
}

export async function loadWhatsNewMark(): Promise<void> {
  if (whatsNew.mark !== '') return;
  try {
    const body = await authFetch<WhatsNewResponse>('/whats-new');
    if (typeof body.mark === 'string') whatsNew.mark = body.mark;
  } catch {
  }
}

export async function loadWhatsNew(): Promise<void> {
  if (whatsNew.mark === '') return;
  try {
    const body = await authFetch<WhatsNewResponse>(
      `/whats-new?since=${encodeURIComponent(whatsNew.mark)}`,
    );
    whatsNew.entries = Array.isArray(body.entries) ? body.entries : [];
    whatsNew.more = typeof body.more === 'number' ? body.more : 0;
  } catch {
  }
}

let started = false;

export interface VersionWatchOptions {
  baselineFromServer?: boolean;
}

let baselineFromServer = false;

export function observeServer(version: unknown, build: unknown): void {
  if (typeof version === 'string' && version !== '') {
    if (baselineFromServer && versionWatch.pageVersion === '') versionWatch.pageVersion = version;
    versionWatch.latestServerVersion = version;
  }
  if (typeof build === 'string' && build !== '') {
    if (baselineFromServer && versionWatch.pageClientBuild === '') versionWatch.pageClientBuild = build;
    versionWatch.latestClientBuild = build;
  }
}

export function startVersionWatch(options: VersionWatchOptions = {}): void {
  if (started) return;
  started = true;
  baselineFromServer = options.baselineFromServer === true;
  void loadWhatsNewMark();
  subscribe('events.hello', (frame: EventFrame) => {
    observeServer(frame.server_version, frame.client_build);
  });
  if (baselineFromServer) void pollClientBuild();
  startClientBuildPoll();
}

interface VersionResponse {
  version?: string;
  client_build?: string;
}

export async function pollClientBuild(): Promise<void> {
  try {
    const body = await authFetch<VersionResponse>('/version');
    observeServer(body.version, body.client_build);
  } catch {
  }
}

function startClientBuildPoll(): void {
  if (typeof document === 'undefined') return;
  resourcePush().pushOrPoll(() => {
    if (document.visibilityState === 'visible') void pollClientBuild();
  }, CLIENT_BUILD_POLL_MS, ['client_build']);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void pollClientBuild();
  });
}

export function dismissVersionBanner(): void {
  versionWatch.dismissedVersion = versionWatch.latestServerVersion;
  versionWatch.dismissedClientBuild = versionWatch.latestClientBuild;
}

export function reloadForNewVersion(): void {
  location.reload();
}
