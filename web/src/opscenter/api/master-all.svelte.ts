
import { untrack } from 'svelte';
import {
  SIZE_MASTER_EVENT,
  SIZE_MASTER_USER_RELEASE_EVENT,
  claimSizeMaster,
  sizeMasters,
  releaseSizeMaster,
  thisTabId,
} from './size-master.svelte';
import { primarySessionId } from './host';
import { sessions } from './sessions.svelte';
import { terminalLayout } from '../engine/layout.svelte';
import { instancesOf } from '../engine/model';
import { kindOf } from '../engine/meta';
import { sessionForSlot } from '../engine/slot-identity';

const STORAGE_KEY = 'carnivore.terminal.master_all';

export const MASTER_ALL_EVENT = 'cloude:master-all';

export const masterAll: { enabled: boolean } = $state({ enabled: readFlag() });

function publish(): void {
  if (typeof window === 'undefined' || typeof CustomEvent !== 'function') return;
  window.dispatchEvent(new CustomEvent(MASTER_ALL_EVENT, { detail: { enabled: masterAll.enabled } }));
}

const heldByMasterAll = new Set<string>();

function soloWindow(): boolean {
  return typeof document !== 'undefined' && document.documentElement.hasAttribute('data-solo');
}

function readFlag(): boolean {
  if (soloWindow()) return false;
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeFlag(on: boolean): void {
  if (soloWindow()) return;
  try {
    if (typeof localStorage === 'undefined') return;
    if (on) localStorage.setItem(STORAGE_KEY, '1');
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
  }
}

export function attachedSessionIds(): string[] {
  const ids = new Set<string>();
  const primary = primarySessionId();
  if (primary) ids.add(primary);
  for (const id of instancesOf(terminalLayout.state.layout)) {
    if (kindOf(id) !== 'terminal') continue;
    const name = sessionForSlot(id, sessions.data);
    if (name && !name.startsWith('row:')) ids.add(name);
  }
  return [...ids];
}

const claimsInFlight = new Set<string>();

const releasedByUser = new Set<string>();

function syncMasterAll(): void {
  if (!masterAll.enabled) return;
  const me = thisTabId();
  for (const id of attachedSessionIds()) {
    if (releasedByUser.has(id) || claimsInFlight.has(id)) continue;
    if (heldByMasterAll.has(id) && me && sizeMasters[id] === me) continue;
    heldByMasterAll.add(id);
    claimsInFlight.add(id);
    claimSizeMaster(id)
      .catch((err) => {
        heldByMasterAll.delete(id);
        console.error('[MasterAll] claim failed:', err);
      })
      .finally(() => claimsInFlight.delete(id));
  }
}

function releaseAllHeld(): void {
  const ids = [...heldByMasterAll];
  heldByMasterAll.clear();
  releasedByUser.clear();
  for (const id of ids) {
    releaseSizeMaster(id).catch((err) => console.error('[MasterAll] release failed:', err));
  }
}

function onUserRelease(event: Event): void {
  const sessionId = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
  if (sessionId && masterAll.enabled) releasedByUser.add(sessionId);
}

function onSizeMasterEvent(event: Event): void {
  const detail = (event as CustomEvent<{ sessionId?: string; master?: string | null }>).detail;
  const sessionId = detail?.sessionId;
  if (!sessionId || !heldByMasterAll.has(sessionId)) return;
  const holder = detail?.master ?? null;
  if (!holder) {
    if (masterAll.enabled && !releasedByUser.has(sessionId) && !claimsInFlight.has(sessionId)) {
      heldByMasterAll.delete(sessionId);
      syncMasterAll();
    }
    return;
  }
  if (holder === thisTabId()) return;
  heldByMasterAll.delete(sessionId);
  if (!masterAll.enabled) return;
  masterAll.enabled = false;
  writeFlag(false);
  publish();
}

export function setMasterAll(on: boolean): void {
  if (soloWindow() || masterAll.enabled === on) return;
  masterAll.enabled = on;
  writeFlag(on);
  publish();
  if (on) syncMasterAll();
  else releaseAllHeld();
}

let stop: (() => void) | null = null;

export function startMasterAll(): () => void {
  if (stop) return stop;
  if (soloWindow()) return () => {};
  const undo = $effect.root(() => {
    $effect(() => {
      void terminalLayout.state.layout;
      void sessions.data;
      untrack(syncMasterAll);
    });
  });
  const onConnect = () => syncMasterAll();
  window.addEventListener('cloude:terminal-connection', onConnect);
  window.addEventListener(SIZE_MASTER_EVENT, onSizeMasterEvent);
  window.addEventListener(SIZE_MASTER_USER_RELEASE_EVENT, onUserRelease);
  if (masterAll.enabled) syncMasterAll();
  stop = () => {
    undo();
    window.removeEventListener('cloude:terminal-connection', onConnect);
    window.removeEventListener(SIZE_MASTER_EVENT, onSizeMasterEvent);
    window.removeEventListener(SIZE_MASTER_USER_RELEASE_EVENT, onUserRelease);
    stop = null;
  };
  return stop;
}
