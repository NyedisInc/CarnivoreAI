/* could not */
import { whenLegacyBootComplete } from '../../lib/legacy-boot';
import { t } from '../../lib/i18n/index.svelte';
import { sessions } from '../api';
import type { SessionInfo } from '../api/types';
import { PRIMARY_SLOT, removeCell } from '../engine/model';
import { isBareTerminal, isLayoutKey } from '../engine/session-layouts';
import { preferencesApi, queueEntry, type PreferencesApi } from '../engine/arrangement-sync.svelte';
import { rekeyEntry, rowIdOfSlot } from '../engine/slot-identity';
import {
  TERMINAL_LAYOUTS_FIELD, parseArrangement, type Arrangement, type ArrangementEntry,
} from '../engine/arrangement-model';
import type { Layout, SlotId } from '../engine/types';
import type { TabGroups } from '../engine/tabs';
import { createLayout, layoutError, listLayouts } from './api';
import { NAME_MAX, displayedTabs, freeName, terminalComponents, toServerShape, visibleTerminals } from './shape';
import { displayName } from './names';

const BACKUP_PREFIX = 'cloudecode.opscenter.layout.migrate.backup.v1:';

const NAME_RETRIES = 6;

let ran = false;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForPrefs(timeoutMs: number): Promise<PreferencesApi | null> {
  const api = preferencesApi();
  if (!api) return null;
  const start = Date.now();
  while (api.status() !== api.HYDRATED) {
    if (Date.now() - start > timeoutMs) return null;
    await sleep(150);
  }
  return api;
}

async function waitForListing(timeoutMs: number): Promise<SessionInfo[] | null> {
  if (sessions.status !== 'ok') await sessions.refresh(true);
  const start = Date.now();
  while (sessions.status !== 'ok') {
    if (Date.now() - start > timeoutMs) return null;
    await sleep(150);
  }
  return sessions.data ?? [];
}

export function tmuxNameOf(key: string): string {
  const at = key.lastIndexOf(':');
  if (at < 0) return key;
  return /^\d+$/.test(key.slice(at + 1)) ? key.slice(0, at) : key;
}

export function epochOf(key: string): number | null {
  const at = key.lastIndexOf(':');
  if (at < 0) return null;
  const suffix = key.slice(at + 1);
  return /^\d+$/.test(suffix) ? Number(suffix) : null;
}

/* could not */
function anchorRowFor(key: string, rows: readonly SessionInfo[]): SessionInfo | null {
  const name = tmuxNameOf(key);
  const epoch = epochOf(key);
  const named = rows.filter((row) => row.tmux_session === name);
  if (epoch === null) return named[0] ?? null;
  return named.find((row) => row.session.tmux_created_epoch === epoch) ?? null;
}

function tabName(tab: string, rows: readonly SessionInfo[]): string {
  const rowId = rowIdOfSlot(tab);
  if (rowId === null) return '';
  const row = rows.find((one) => one.session_row_id === rowId);
  return row ? displayName(row.label, row.tmux_session) : '';
}

function suggestedName(anchorName: string, secondName: string, taken: readonly string[]): string {
  const plain = t('layout.name.suggested', { first: anchorName, second: secondName }).slice(0, NAME_MAX);
  return freeName(plain, taken, (name, number) => t('layout.name.suggested_numbered', { name, number }));
}

async function createMigrated(
  base: string, shape: ReturnType<typeof toServerShape>, sourceKey: string, taken: readonly string[],
): Promise<string | null> {
  let pool = [...taken];
  for (let attempt = 0; attempt < NAME_RETRIES; attempt += 1) {
    const name = freeName(base, pool, (n, i) => t('layout.name.suggested_numbered', { name: n, number: i }));
    try {
      await createLayout(name, shape, sourceKey);
      return name;
    } catch (error) {
      const refused = layoutError(error);
      if (refused.code !== 'layout_name_taken') return null;
      pool = [...pool, name];
    }
  }
  return null;
}

export function stripSplit(layout: Layout, groups: TabGroups): ArrangementEntry {
  let next = layout;
  for (const component of terminalComponents(layout)) {
    if (component === PRIMARY_SLOT) continue;
    next = removeCell(next, component as SlotId);
  }
  const ownTabs = groups[PRIMARY_SLOT]?.tabs?.length ? groups[PRIMARY_SLOT]!.tabs : [PRIMARY_SLOT];
  return { layout: isBareTerminal(next) ? null : next, groups: { [PRIMARY_SLOT]: { tabs: ownTabs } } };
}

function backup(key: string, entry: ArrangementEntry): void {
  try {
    localStorage.setItem(BACKUP_PREFIX + key, JSON.stringify(entry));
  } catch {
  }
}

/* could not */
async function migrateEntry(
  key: string, entry: ArrangementEntry, rows: readonly SessionInfo[], taken: readonly string[],
): Promise<string | null> {
  const layout = entry.layout;
  if (isLayoutKey(key) || !layout || visibleTerminals(layout) < 2) return null;
  const anchorRow = anchorRowFor(key, rows);
  const anchorRowId = anchorRow?.session_row_id;
  if (!anchorRow || typeof anchorRowId !== 'number') return null;
  const rekeyed = rekeyEntry({ layout, groups: entry.groups, active: {} }, rows, true);
  const finalLayout = rekeyed.layout ?? layout;
  const finalGroups = rekeyed.groups ?? entry.groups;
  if (visibleTerminals(finalLayout) < 2) return null; // could not
  const shape = toServerShape(finalLayout, finalGroups, anchorRowId);
  const anchorName = displayName(anchorRow.label, anchorRow.tmux_session);
  const second = displayedTabs(finalLayout, finalGroups).find((tab) => tab !== PRIMARY_SLOT) ?? '';
  const base = suggestedName(anchorName, second ? tabName(second, rows) : '', taken);
  const sourceKey = `terminal_layouts:${key}`;
  const name = await createMigrated(base, shape, sourceKey, taken);
  if (!name) return null;
  backup(key, entry);
  queueEntry(key, stripSplit(layout, entry.groups));
  return name;
}

async function scan(api: PreferencesApi, rows: readonly SessionInfo[]): Promise<void> {
  const arrangement: Arrangement | null = parseArrangement(api.committedValue(TERMINAL_LAYOUTS_FIELD));
  if (!arrangement) return;
  let taken: string[];
  try {
    taken = (await listLayouts()).layouts.map((one) => one.name);
  } catch {
    return;
  }
  for (const [key, entry] of Object.entries(arrangement.sessions)) {
    try {
      const name = await migrateEntry(key, entry, rows, taken);
      if (name) taken = [...taken, name];
    } catch (error) {
      console.warn('[layouts migration] one entry failed, left for a later boot', key, error);
    }
  }
}

export async function runLayoutMigration(
  target: Window | null = typeof window !== 'undefined' ? window : null,
): Promise<void> {
  if (ran) return;
  ran = true;
  await new Promise<void>((resolve) => whenLegacyBootComplete(target, resolve));
  const api = await waitForPrefs(8000);
  if (!api) return;
  const rows = await waitForListing(8000);
  if (!rows) return;
  await scan(api, rows);
}

export function resetLayoutMigration(): void {
  ran = false;
}
