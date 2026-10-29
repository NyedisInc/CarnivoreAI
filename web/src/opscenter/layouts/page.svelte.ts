import { tick } from 'svelte';
import { terminalLayout } from '../engine/layout.svelte';
import { adoptGroups, cloneTabs, openTab, tabsFor } from '../engine/tab-groups.svelte';
import { bindPrimary, setBindClaim } from '../engine/primary-bind';
import { gestureActive } from '../engine/pointer';
import { focusTab } from '../engine/tab-drag';
import { inputFocus } from '../lib/input-focus.svelte';
import { PRIMARY_SLOT } from '../engine/model';
import { currentNav, beginNav, type NavToken } from '../../lib/launchpad/nav-generation';
import { t } from '../../lib/i18n/index.svelte';
import { openSession, primarySessionId, primaryTmuxEpoch, primaryTmuxName } from '../api/host';
import { sessions, subscribe, startEvents } from '../api';
import { openModal } from '../../lib/modal';
import { closeMenuPagesExcept } from '../../lib/menu-page/menu-page-shell.svelte';
import AllDownModal from './AllDownModal.svelte';
import {
  layoutError, listLayouts, removeMember, renewActive, type LayoutMember, type LayoutWrite, type SavedLayout,
} from './api';
import { fromServerShape, rowSlot, terminalComponents } from './shape';
import { PENDING_KEY, clearLayoutMode, layoutActive, layoutKeyOf, layoutMode, memberForRow } from './mode.svelte';
import { currentShape, dropPending, flushShape, flushShapeFinal, noteSaved, savePending, startSaveTarget, whileApplying } from './save-target.svelte';
import { abortNaming, abortNamingIfMoved, isNaming, namingSurvives, refusalLine, setSavedHandler } from './transition.svelte';
import { displayName, liveMemberRowFor, liveRowFor, urlSlug } from './names';
import { rememberLastView } from '../../lib/drawer/last-view';
import { layoutByUuid } from '../../lib/layouts-bridge/api.svelte';
import { withScrollback } from '../cells/terminal-live/client';
import { setParking } from '../cells/terminal-live/parking';
import { TERMINAL_CONTAINER_ID } from '../cells/terminal/adopt';
import { mountLayoutCommandBar } from './command-bar-mount';
import { syncBroadcastFlags } from './broadcast.svelte';

export const LEASE_MS = 60_000;

const HOLD_MS = 10_000;

let holdTimer: ReturnType<typeof setTimeout> | undefined;
let heldNav: NavToken = null;
let leaseTimer: ReturnType<typeof setInterval> | undefined;
let started = false;
const surfaces = { grid: false, phone: false };

interface RouterApi {
  rejectTarget?: (name: string) => void;
  showError?: (message: string) => void;
}
function router(): RouterApi | null {
  return ((globalThis as { Router?: RouterApi }).Router as RouterApi | undefined) ?? null;
}

export function layoutPath(uuid: string): string {
  return `/layout/${encodeURIComponent(uuid)}`;
}

function showPath(uuid: string, push: boolean): void {
  const path = layoutPath(uuid);
  try {
    if (globalThis.location?.pathname === path) return;
    if (push) globalThis.history?.pushState({}, '', path);
    else globalThis.history?.replaceState({}, '', path);
  } catch {
  }
}

function showSessionPath(): void {
  const app = (globalThis as { App?: { _syncSessionUrl?: (name: string, replace: boolean) => void } }).App;
  const name = primaryTmuxName();
  if (name && typeof app?._syncSessionUrl === 'function') app._syncSessionUrl(name, true);
}

function onTerminalScreen(): boolean {
  return (globalThis as { App?: { currentScreen?: string } }).App?.currentScreen === 'terminal';
}

function announce(line: string): void {
  terminalLayout.announce(line);
}

function pickAnchor(
  members: LayoutMember[],
): { member: LayoutMember; sessionId: string; tmux: string; row: unknown } | null {
  const ordered = [...members].sort((a, b) => a.position - b.position);
  for (const member of ordered) {
    const row = liveMemberRowFor(member.session_row_id);
    if (row?.session?.id) return { member, sessionId: row.session.id, tmux: row.tmux_session ?? '', row };
  }
  return null;
}

function paneElement(): HTMLElement | null {
  return typeof document === 'undefined' ? null : document.getElementById(TERMINAL_CONTAINER_ID);
}

function setHolding(on: boolean): void {
  layoutMode.holding = on;
  const pane = paneElement();
  if (pane) pane.style.visibility = on ? 'hidden' : '';
  if (holdTimer !== undefined) clearTimeout(holdTimer);
  holdTimer = on ? setTimeout(() => setHolding(false), HOLD_MS) : undefined;
}

function nothingOnScreen(): boolean {
  const screen = (globalThis as { App?: { currentScreen?: string } }).App?.currentScreen;
  return !screen || screen === 'auth';
}

/* nothing at all the home screen */
function landHomeIfBlank(): void {
  if (!nothingOnScreen()) return;
  (globalThis as { App?: { showLaunchpad?: () => void } }).App?.showLaunchpad?.();
}

function returnToExistingTerminal(session: unknown): void {
  const app = (globalThis as { App?: { returnToExistingTerminal?: (s: unknown) => unknown } }).App;
  if (typeof app?.returnToExistingTerminal === 'function') void app.returnToExistingTerminal(session);
}

async function bindAnchor(row: unknown, nav: NavToken): Promise<void> {
  const bound = await withScrollback(row);
  if (currentNav() !== nav) return;
  returnToExistingTerminal(bound);
}

/* there is nothing */
async function offerAllDown(saved: SavedLayout, nav: NavToken, uuid: string, fromUrl: boolean): Promise<void> {
  landHomeIfBlank();
  const revived = await openModal(AllDownModal, { layout: saved });
  if (currentNav() !== nav) return;
  if (revived) await openLayout(uuid, fromUrl);
}

function applyLayout(layout: SavedLayout, anchorRowId: number, anchorSessionId: string, anchorTmux: string, push: boolean): boolean {
  const drawn = fromServerShape(layout.shape, anchorRowId);
  if (!drawn?.layout) return false;
  if (layoutActive() && layoutMode.uuid !== layout.layout_uuid) leave(false);
  const key = layoutKeyOf(layout.layout_uuid);
  const fresh = layoutMode.uuid !== layout.layout_uuid;
  layoutMode.uuid = layout.layout_uuid;
  layoutMode.name = layout.name;
  layoutMode.revision = layout.revision;
  layoutMode.members = layout.members;
  layoutMode.anchorRowId = anchorRowId;
  layoutMode.anchorSessionId = anchorSessionId;
  layoutMode.anchorTmux = anchorTmux;
  if (fresh) layoutMode.phoneTab = PRIMARY_SLOT;
  whileApplying(() => {
    if (terminalLayout.session !== key) terminalLayout.bindKey(key, drawn.layout!);
    terminalLayout.adopt(drawn.layout);
    adoptGroups(key, drawn.groups);
  });
  noteSaved(currentShape());
  heldNav = currentNav();
  showPath(layout.layout_uuid, push);
  startLease(layout.layout_uuid);
  rememberLastView({ kind: 'layout', uuid: layout.layout_uuid });
  return true;
}

function leave(rebind: boolean): void {
  if (!layoutActive()) return;
  void flushShapeFinal();
  stopLease();
  dropPending();
  setHolding(false);
  clearLayoutMode();
  heldNav = null;
  if (rebind) bindPrimary(terminalLayout, primarySessionId(), primaryTmuxName(), primaryTmuxEpoch());
}

function claimBind(sessionId: string): boolean | 'hold' {
  if (isNaming()) return namingSurvives(sessionId);
  if (!layoutActive()) return false;
  if (currentNav() !== heldNav) {
    leave(false);
    return false;
  }
  if (!layoutMode.holding) return true;
  if (sessionId !== layoutMode.anchorSessionId) return 'hold';
  setHolding(false);
  return true;
}

export function pathFor(slug: string): string | null {
  abortNamingIfMoved();
  if (!layoutActive()) return null;
  if (slug === urlSlug(layoutMode.anchorTmux) && currentNav() === heldNav) return layoutPath(layoutMode.uuid);
  leave(true);
  return null;
}

/* could not be read */
async function fetchLayout(uuid: string): Promise<{ saved: SavedLayout | null; held: boolean; error?: string }> {
  try {
    const list = await listLayouts();
    if (list.status !== 'ok') return { saved: null, held: false, error: list.detail ?? '' };
    return { saved: list.layouts.find((one) => one.layout_uuid === uuid) ?? null, held: false };
  } catch (error) {
    return { saved: null, held: false, error: layoutError(error).detail };
  }
}

function takeKeyboard(tab: string): void {
  inputFocus.claim(tab);
  const nav = currentNav();
  let tries = 0;
  const attempt = (): void => {
    if (currentNav() !== nav) return;
    focusTab(tab);
    const held = document.activeElement?.closest<HTMLElement>('[data-tab-pane]')?.dataset['tabPane'] === tab;
    if (!held && ++tries < 40) setTimeout(attempt, 150);
  };
  void tick().then(attempt);
}

export function focusMember(sessionUuid: string, keyboard = false): boolean {
  const member = layoutMode.members.find((one) => one.session_uuid === sessionUuid);
  if (!member) return false;
  const tab = member.session_row_id === layoutMode.anchorRowId ? PRIMARY_SLOT : rowSlot(member.session_row_id);
  for (const slot of terminalComponents(terminalLayout.state.layout)) {
    if (tabsFor(terminalLayout, slot).includes(tab)) {
      openTab(terminalLayout, slot, tab);
      if (keyboard) takeKeyboard(tab);
      return true;
    }
  }
  return false;
}

/* on the terminal screen */
export async function openLayout(uuid: string, fromUrl = false, focusSession = ''): Promise<void> {
  start();
  const alreadyOpen = layoutActive() && layoutMode.uuid === uuid && onTerminalScreen();
  if (alreadyOpen) closeMenuPagesExcept(null);
  if (focusSession && alreadyOpen) {
    focusMember(focusSession);
    return;
  }
  const nav = beginNav('layout:' + uuid);
  if (layoutActive()) void flushShape();
  const heldRow = layoutByUuid(uuid);
  const held = heldRow ? ($state.snapshot(heldRow) as unknown as SavedLayout) : null;
  const found = held ? { saved: held, held: true } : await fetchLayout(uuid);
  if (currentNav() !== nav) return;
  if (found.error !== undefined) {
    landHomeIfBlank();
    router()?.showError?.(t('layout.error.unavailable', { reason: found.error }));
    return;
  }
  const saved = found.saved;
  if (!saved) {
    landHomeIfBlank();
    if (fromUrl) router()?.rejectTarget?.(uuid);
    else announce(t('layout.error.not_found'));
    return;
  }
  let anchor = sessions.data ? pickAnchor(saved.members) : null;
  if (!anchor) {
    await sessions.refresh(true);
    if (currentNav() !== nav) return;
    anchor = pickAnchor(saved.members);
  }
  if (!anchor) {
    await offerAllDown(saved, nav, uuid, fromUrl);
    return;
  }
  const push = !fromUrl;
  const inPlace = anchor.sessionId === primarySessionId() && onTerminalScreen();
  applyLayout(saved, anchor.member.session_row_id, anchor.sessionId, anchor.tmux, push);
  if (found.held) void followRemote();
  if (focusSession) focusMember(focusSession);
  if (inPlace) {
    setHolding(false);
    return;
  }
  setHolding(true);
  await bindAnchor(anchor.row, nav);
}

export function openFromUrl(uuid: string): Promise<void> {
  return openLayout(uuid, true);
}

function landOnSurvivor(write: LayoutWrite): void {
  const survivor = write.survivor;
  leave(false);
  const row = liveRowFor(survivor?.session_row_id ?? null);
  const name = row ? displayName(row.label, row.tmux_session) : '';
  announce(t('layout.removed_to_one', { name }));
  if (row?.session?.id && row.session.id !== primarySessionId()) {
    openSession(row.session.id, row.tmux_session ?? null);
    return;
  }
  bindPrimary(terminalLayout, primarySessionId(), primaryTmuxName(), primaryTmuxEpoch());
  showSessionPath();
}

export async function removeAnchor(): Promise<void> {
  if (!layoutActive()) return;
  const uuid = layoutMode.uuid;
  const member = memberForRow(layoutMode.anchorRowId);
  if (!member) return;
  await flushShape();
  let write: LayoutWrite;
  try {
    write = await removeMember(uuid, member.session_uuid);
  } catch (error) {
    announce(refusalLine(layoutError(error)));
    return;
  }
  if (layoutMode.uuid !== uuid) return;
  if (write.deleted) {
    landOnSurvivor(write);
    return;
  }
  await openLayout(uuid);
}

export async function anchorGone(): Promise<void> {
  if (!layoutActive()) return;
  await openLayout(layoutMode.uuid);
}

function startLease(uuid: string): void {
  stopLease();
  const renew = (): void => {
    if (layoutMode.uuid !== uuid) return;
    renewActive(uuid).catch((error: unknown) => {
      if (layoutError(error).status === 404 && layoutMode.uuid === uuid) missing();
    });
  };
  renew();
  leaseTimer = setInterval(renew, LEASE_MS);
}

function stopLease(): void {
  if (leaseTimer !== undefined) clearInterval(leaseTimer);
  leaseTimer = undefined;
}

function missing(): void {
  leave(true);
  announce(t('layout.error.not_found'));
  showSessionPath();
}

async function followRemote(): Promise<void> {
  if (!layoutActive()) return;
  const uuid = layoutMode.uuid;
  let list;
  try {
    list = await listLayouts();
  } catch {
    return;
  }
  if (layoutMode.uuid !== uuid || list.status !== 'ok') return;
  const saved = list.layouts.find((one) => one.layout_uuid === uuid);
  if (!saved) {
    missing();
    return;
  }
  layoutMode.name = saved.name;
  syncBroadcastFlags(saved.members);
  if (saved.revision <= layoutMode.revision) return;
  if (gestureActive() || savePending()) {
    setTimeout(() => void followRemote(), 300);
    return;
  }
  adoptStored(saved);
}

function adoptStored(saved: SavedLayout): void {
  const anchorRowId = layoutMode.anchorRowId;
  if (anchorRowId !== null && saved.members.some((one) => one.session_row_id === anchorRowId)) {
    applyLayout(saved, anchorRowId, layoutMode.anchorSessionId, layoutMode.anchorTmux, false);
    return;
  }
  void openLayout(saved.layout_uuid);
}

export function noteSurface(which: 'grid' | 'phone', up: boolean): void {
  surfaces[which] = up;
  if (which === 'grid') setParking(up);
  if (up) return;
  queueMicrotask(() => {
    if (!surfaces.grid && !surfaces.phone) {
      if (isNaming()) abortNaming();
      leave(false);
    }
  });
}

function enterSaved(layout: SavedLayout, anchorSessionId: string, anchorRowId: number): void {
  beginNav('layout:' + layout.layout_uuid);
  whileApplying(() => cloneTabs(PENDING_KEY, layoutKeyOf(layout.layout_uuid)));
  applyLayout(layout, anchorRowId, anchorSessionId, primaryTmuxName(), true);
}

function watchAnchorRow(): void {
  if (typeof document === 'undefined') return;
  const onRow = (event: Event): void => {
    if (!layoutActive()) return;
    if (event instanceof KeyboardEvent && event.key !== 'Enter') return;
    const row = (event.target as Element | null)?.closest?.('.session-sidebar-row') as HTMLElement | null;
    if (!row || row.dataset['name'] !== layoutMode.anchorTmux) return;
    leave(true);
    showSessionPath();
  };
  document.addEventListener('click', onRow, true);
  document.addEventListener('keydown', onRow, true);
}

function holdsSession(sessionId: string, tmuxName: string): boolean {
  if (!layoutActive()) return false;
  if ((sessionId && sessionId === layoutMode.anchorSessionId) || (tmuxName && tmuxName === layoutMode.anchorTmux)) return true;
  return layoutMode.members.some((member) => {
    const row = liveRowFor(member.session_row_id);
    return !!row && ((!!tmuxName && row.tmux_session === tmuxName) || (!!sessionId && row.session.id === sessionId));
  });
}

export function start(): void {
  if (started) return;
  started = true;
  mountLayoutCommandBar();
  setBindClaim(claimBind);
  setSavedHandler(enterSaved);
  startSaveTarget({
    landed: () => undefined,
    deleted: landOnSurvivor,
    adopt: adoptStored,
    missing,
    announce: (_line, kind, reason) => {
      if (kind === 'merged') announce(t('opscenter.tabs.sync_merged'));
      else if (kind === 'lost') announce(t('layout.error.stale'));
      else announce(t('layout.error.save_failed', { reason: reason ?? '' }));
    },
  });
  watchAnchorRow();
  startEvents();
  subscribe('sessions.changed', (frame) => {
    if ((frame as { reason?: string }).reason === 'layouts') void followRemote();
  });
}

export const layoutPageApi = {
  openFromUrl,
  openLayout: (uuid: string, focusSession = '') => openLayout(uuid, false, focusSession),
  focusMember,
  pathFor,
  isActive: layoutActive,
  holds: holdsSession,
  current: () => (layoutActive() ? { uuid: layoutMode.uuid, name: layoutMode.name } : null),
};
