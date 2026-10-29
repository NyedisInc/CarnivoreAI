import { terminalLayout } from '../engine/layout.svelte';
import { cloneTabs, forgetTabs, groupsFor } from '../engine/tab-groups.svelte';
import { isLayoutKey } from '../engine/session-layouts';
import { PRIMARY_SLOT } from '../engine/model';
import { rekeyEntry } from '../engine/slot-identity';
import { openModal } from '../../lib/modal';
import { currentNav, type NavToken } from '../../lib/launchpad/nav-generation';
import { t } from '../../lib/i18n/index.svelte';
import { primarySessionId } from '../api/host';
import { sessions } from '../api';
import type { Layout } from '../engine/types';
import LayoutNameModal from './LayoutNameModal.svelte';
import {
  createLayout, deleteLayout, layoutError, listLayouts, type LayoutError, type SavedLayout,
} from './api';
import { LAYOUT_LIMIT, NAME_MAX, displayedTabs, freeName, toServerShape } from './shape';
import { PENDING_KEY, layoutMode } from './mode.svelte';
import { nameForTab, primaryRowId } from './names';

interface Naming {
  agentKey: string;
  agentLayout: Layout;
  anchorSessionId: string;
  anchorRowId: number;
  nav: NavToken;
  cancel: (() => void) | null;
}

let naming: Naming | null = null;

let onSaved: ((layout: SavedLayout, anchorSessionId: string, anchorRowId: number) => void) | null = null;

export function setSavedHandler(fn: typeof onSaved): void {
  onSaved = fn;
}

export function refusalLine(refused: LayoutError): string {
  switch (refused.code) {
    case 'layout_name_taken':
      return t('layout.error.name_taken');
    case 'layout_limit':
      return t('layout.error.limit', { max: LAYOUT_LIMIT });
    case 'layout_name_invalid':
      return t('layout.error.name_invalid');
    case 'member_unresolved':
      return t('layout.error.member_unresolved');
    case 'layout_too_few_members':
      return t('layout.error.too_few_members');
    case 'layouts_unavailable':
      return t('layout.error.unavailable', { reason: refused.detail });
    default:
      return t('layout.error.save_failed', { reason: refused.detail });
  }
}

export function splitThrough<T>(apply: () => T, landed: (result: T) => boolean, refused: T): T {
  const store = terminalLayout;
  const key = store.session;
  if (store.page !== 'terminal' || naming || !key || isLayoutKey(key)) return apply();
  const anchorSessionId = primarySessionId();
  const anchorRowId = primaryRowId();
  if (anchorRowId === null) {
    store.announce(t('layout.error.member_unresolved'));
    return refused;
  }
  const agentLayout = $state.snapshot(store.state.layout) as Layout;
  store.bindKey(PENDING_KEY, structuredClone(agentLayout));
  cloneTabs(key, PENDING_KEY);
  let result: T;
  try {
    result = apply();
  } catch (error) {
    putBack(key, agentLayout);
    throw error;
  }
  if (!landed(result)) {
    putBack(key, agentLayout);
    return result;
  }
  naming = { agentKey: key, agentLayout, anchorSessionId, anchorRowId, nav: currentNav(), cancel: null };
  layoutMode.naming = true;
  void askName(naming);
  return result;
}

function putBack(agentKey: string, agentLayout: Layout): void {
  if (terminalLayout.session === PENDING_KEY) terminalLayout.bindKey(agentKey, agentLayout);
  forgetTabs(PENDING_KEY);
}

function pendingShape(anchorRowId: number) {
  const layout = $state.snapshot(terminalLayout.state.layout) as Layout;
  const groups = $state.snapshot(groupsFor(PENDING_KEY));
  const keyed = rekeyEntry({ layout, groups, active: {} }, sessions.data ?? [], false);
  return toServerShape(keyed.layout ?? layout, keyed.groups, anchorRowId);
}

async function suggestion(): Promise<string> {
  const layout = $state.snapshot(terminalLayout.state.layout) as Layout;
  const others = displayedTabs(layout, $state.snapshot(groupsFor(PENDING_KEY))).filter((tab) => tab !== PRIMARY_SLOT);
  const plain = t('layout.name.suggested', {
    first: nameForTab(PRIMARY_SLOT),
    second: others[0] ? nameForTab(others[0]) : '',
  }).slice(0, NAME_MAX);
  let taken: string[] = [];
  try {
    taken = (await listLayouts()).layouts.map((one) => one.name);
  } catch {
  }
  return freeName(plain, taken, (name, number) => t('layout.name.suggested_numbered', { name, number }));
}

async function askName(mine: Naming): Promise<void> {
  let created: SavedLayout | null = null;
  let posting: Promise<string> | null = null;
  const suggested = await suggestion();
  if (naming !== mine) return;
  const post = async (name: string): Promise<string> => {
    try {
      const write = await createLayout(name, pendingShape(mine.anchorRowId));
      created = write.layout;
      return created ? '' : t('layout.error.save_failed', { reason: '' });
    } catch (error) {
      return refusalLine(layoutError(error));
    }
  };
  const save = (name: string): Promise<string> => {
    posting = post(name);
    return posting;
  };
  const saved = await openModal(LayoutNameModal, {
    suggested,
    save,
    watchAbort: (cancel: () => void) => {
      mine.cancel = cancel;
      return () => {
        if (mine.cancel === cancel) mine.cancel = null;
      };
    },
  });
  if (posting) await posting;
  const stillMine = naming === mine;
  naming = null;
  layoutMode.naming = false;
  const layout = created as SavedLayout | null;
  if (saved && layout && stillMine && terminalLayout.session === PENDING_KEY && onSaved) {
    onSaved(layout, mine.anchorSessionId, mine.anchorRowId);
    forgetTabs(PENDING_KEY);
    return;
  }
  if (layout) void deleteLayout(layout.layout_uuid).catch(() => undefined);
  putBack(mine.agentKey, mine.agentLayout);
}

export function namingSurvives(sessionId: string): boolean {
  if (!naming) return false;
  if (sessionId === naming.anchorSessionId && currentNav() === naming.nav) return true;
  abortNaming();
  return false;
}

export function abortNaming(): void {
  const mine = naming;
  if (!mine) return;
  if (mine.cancel) mine.cancel();
  else {
    naming = null;
    layoutMode.naming = false;
    putBack(mine.agentKey, mine.agentLayout);
  }
}

export function abortNamingIfMoved(): void {
  if (naming && currentNav() !== naming.nav) abortNaming();
}

export function isNaming(): boolean {
  return naming !== null;
}
