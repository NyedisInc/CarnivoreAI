import type { CplugRow } from '../../lib/plugins-page/cplugs-adapter';
import { CPLUGS_TOPIC, POLL_MS, pluginsStore } from '../../lib/plugins/store.svelte';
import type { CplugManifest } from '../sdk';

export { CPLUGS_TOPIC, POLL_MS };

const DEFAULT_GRANTED = new Set(['sessions.read', 'notify']);
const DEFAULT_GRANTED_READ = new Set(['sessions', 'sessions.read', 'projects']);
const DEFAULT_GRANTED_WRITE = new Set(['notify']);
const FEED_EVENT_FAMILIES = new Set(['feed.meta', 'feed.scrubbed', 'feed.raw', 'mcp.health']);

export const cplugEnablement = $state<{ read: boolean; enabled: Record<string, boolean>; settings: Record<string, Record<string, unknown>> }>({
  read: false,
  enabled: {},
  settings: {},
});

function applyStoreRows(rows: readonly CplugRow[]): void {
  const next: Record<string, boolean> = {};
  const settings: Record<string, Record<string, unknown>> = {};
  for (const row of rows) {
    if (row.state === 'removed') continue;
    next[row.id] = row.enabled === true;
    settings[row.id] = row.settings && typeof row.settings === 'object' ? { ...row.settings } : {};
  }
  cplugEnablement.enabled = next;
  cplugEnablement.settings = settings;
  cplugEnablement.read = true;
}

let bridgeWired = false;
function ensureBridge(): void {
  if (bridgeWired) return;
  bridgeWired = true;
  pluginsStore.onSync(applyStoreRows);
  pluginsStore.onReset(() => {
    following = false;
    stopRows?.();
    stopRows = null;
    stopAcquire?.();
    stopAcquire = null;
    cplugEnablement.enabled = {};
    cplugEnablement.settings = {};
    cplugEnablement.read = false;
  });
}

export function defaultEnabled(manifest: CplugManifest): boolean {
  if (manifest.tier === 'dev') return false;
  if (manifest.tier !== undefined && manifest.tier !== 'core' && manifest.tier !== 'builtin') return false;
  if (manifest.tier === 'core' || manifest.default_enabled === true) return true;
  if (manifest.default_enabled === false) return false;
  const perms = manifest.permissions;
  const appOk = (perms?.app ?? []).every((p) => DEFAULT_GRANTED.has(p));
  const readOk = (perms?.read ?? []).every((p) => DEFAULT_GRANTED_READ.has(p));
  const writeOk = (perms?.write ?? []).every((p) => DEFAULT_GRANTED_WRITE.has(p));
  const netEmpty =
    (perms?.network?.length ?? 0) === 0
    && (perms?.lan?.length ?? 0) === 0
    && (perms?.services?.length ?? 0) === 0
    && (perms?.events?.length ?? 0) === 0;
  const declaredWebhooks = new Set(Object.keys(manifest.webhooks ?? {}));
  const webhooksEmpty = declaredWebhooks.size === 0;
  const servicesOk = (manifest.services?.consumes?.length ?? 0) === 0;
  const eventsEmitOk = (manifest.events?.emit?.length ?? 0) === 0;
  const eventsOnOk = (manifest.events?.on ?? []).every(
    (e) => FEED_EVENT_FAMILIES.has(e) || (e.startsWith('webhook.') && declaredWebhooks.has(e.slice(8))),
  );
  const uiContributeEmpty =
    Object.keys(manifest.ui?.contribute ?? {}).length === 0
    && Object.keys(manifest.ui_contribute ?? {}).length === 0;
  return appOk && readOk && writeOk && netEmpty && webhooksEmpty && servicesOk && eventsEmitOk && eventsOnOk && uiContributeEmpty;
}

export function cplugEnabled(manifest: CplugManifest): boolean {
  const known = cplugEnablement.enabled[manifest.id];
  return known ?? defaultEnabled(manifest);
}

export function cplugSetting<T>(manifest: CplugManifest, key: string, fallback: T): T {
  const value = cplugEnablement.settings[manifest.id]?.[key];
  return value === undefined ? fallback : (value as T);
}

export function cplugRow(id: string): CplugRow | undefined {
  return pluginsStore.rowOf(id);
}

export async function refreshEnablement(): Promise<void> {
  ensureBridge();
  await pluginsStore.refresh({ force: true, allowSignedOut: true });
}

export function followCplugRow(
  id: string,
  onRow: (row: CplugRow | undefined) => void,
  opts: { readonly onReset?: () => void; readonly onSettled?: () => void } = {},
): () => void {
  ensureBridge();
  let active = true;
  let offSync: () => void = () => {};
  let offReset: () => void = () => {};
  let stopRowAcquire: () => void = () => {};
  const stop = (): void => {
    if (!active) return;
    active = false;
    offSync();
    offReset();
    stopRowAcquire();
  };
  offSync = pluginsStore.onSync((rows) => {
    if (!active) return;
    onRow(rows.find((r) => r.id === id));
    opts.onSettled?.();
  });
  offReset = pluginsStore.onReset(() => {
    stop();
    opts.onReset?.();
  });
  stopRowAcquire = pluginsStore.acquire({ allowSignedOut: true });
  if (pluginsStore.read) {
    onRow(pluginsStore.rowOf(id));
    opts.onSettled?.();
  } else if (opts.onSettled) {
    void pluginsStore.refresh({ allowSignedOut: true }).finally(() => {
      if (active) opts.onSettled?.();
    });
  }
  return stop;
}

let following = false;
let stopRows: (() => void) | null = null;
let stopAcquire: (() => void) | null = null;

export function followEnablement(changed: () => void = () => {}): void {
  ensureBridge();
  if (following) return;
  following = true;
  stopRows = pluginsStore.onRows(() => changed());
  stopAcquire = pluginsStore.acquire({ allowSignedOut: true });
}
