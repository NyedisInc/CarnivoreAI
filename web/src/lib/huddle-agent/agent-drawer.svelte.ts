import { agentIdFromHash, agentPage, type AgentDrawerTab } from '../../cplugs/huddle/agents/agent-page.svelte';
import { DEFAULT_WIDTH_PX, readWidth as readLeftWidth } from '../drawer/resize';

export const AGENT_DRAWER_WIDTH_KEY = 'carnivore.huddle.agent-drawer.width';
export const AGENT_DRAWER_MIN_PX = 240;
export const AGENT_DRAWER_MAX_PX = 720;

export const agentDrawer = $state<{ id: number | null; tab: AgentDrawerTab; width: number | null }>({ id: null, tab: 'chat', width: null });

export function clampDrawerWidth(px: number): number {
  return Math.min(AGENT_DRAWER_MAX_PX, Math.max(AGENT_DRAWER_MIN_PX, Math.round(px)));
}

export function leftDrawerWidth(): number {
  return readLeftWidth() ?? DEFAULT_WIDTH_PX;
}

export function storedDrawerWidth(): number | null {
  try {
    const raw = window.localStorage.getItem(AGENT_DRAWER_WIDTH_KEY);
    const n = raw === null ? NaN : Number(raw);
    return Number.isFinite(n) ? clampDrawerWidth(n) : null;
  } catch {
    return null;
  }
}

export function drawerWidth(): number {
  return agentDrawer.width ?? storedDrawerWidth() ?? leftDrawerWidth();
}

export function setDrawerWidth(px: number, persist: boolean): number {
  const width = clampDrawerWidth(px);
  agentDrawer.width = width;
  if (persist) {
    try {
      window.localStorage.setItem(AGENT_DRAWER_WIDTH_KEY, String(width));
    } catch {
    }
  }
  return width;
}

export function resetDrawerWidth(): void {
  agentDrawer.width = null;
  try {
    window.localStorage.removeItem(AGENT_DRAWER_WIDTH_KEY);
  } catch {
  }
}

export function openAgentDrawer(id: number): void {
  if (agentDrawer.id !== id) agentDrawer.tab = 'chat';
  agentDrawer.id = id;
}

export function closeAgentDrawer(): boolean {
  const was = agentDrawer.id !== null;
  if (was && agentPage.id === agentDrawer.id && agentIdFromHash(typeof location === 'undefined' ? null : location.hash) === null) agentPage.id = null;
  agentDrawer.id = null;
  return was;
}

export function drawerAnchorLeft(): number {
  const open = document.querySelector('.session-sidebar-panel--open');
  return open ? Math.round(open.getBoundingClientRect().right) : 0;
}

export const AGENT_DRAWER_DOCK_MIN_PX = 1024;
export const AGENT_DRAWER_DOCKED_CLASS = 'agent-drawer-docked';

export function dockBesideTerminal(open: boolean, width: number): boolean {
  const body = document.body;
  const dock = open && window.innerWidth >= AGENT_DRAWER_DOCK_MIN_PX;
  const was = body.classList.contains(AGENT_DRAWER_DOCKED_CLASS);
  if (!dock && !was) return false;
  if (dock) body.style.setProperty('--dock-offset', `${drawerAnchorLeft() + Math.min(width, Math.round(window.innerWidth * 0.85))}px`);
  else body.style.removeProperty('--dock-offset');
  body.classList.toggle(AGENT_DRAWER_DOCKED_CLASS, dock);
  const fit = (window as { TerminalLayout?: { requestFit?(why: string): void } }).TerminalLayout;
  if (typeof fit?.requestFit === 'function') fit.requestFit('agent-drawer-dock');
  return dock;
}

export function widthFromPointer(clientX: number, left: number): number {
  return clientX - left;
}

const RAIL_SLOT_ID = 'session-sidebar-wrail';

export interface PhoneFrame {
  top: number;
  left: number;
  height: number;
}

export function phoneFrame(): PhoneFrame {
  const vv = window.visualViewport;
  const viewTop = vv ? vv.offsetTop : 0;
  const viewBottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
  const rail = document.getElementById(RAIL_SLOT_ID)?.getBoundingClientRect();
  const railShown = !!rail && rail.right > 0 && rail.height > 0;
  const top = Math.max(viewTop, railShown ? Math.round(rail.top) : 0);
  return { top, left: railShown ? Math.max(0, Math.round(rail.right)) : 0, height: Math.max(0, Math.round(viewBottom - top)) };
}

export const PHONE_LOCK_CLASS = 'had-phone-open';

export const EDGE_SWIPE_START_PX = 24;
export const EDGE_SWIPE_MIN_PX = 64;

export function isEdgeSwipeBack(start: { x: number; y: number }, end: { x: number; y: number }, left: number): boolean {
  const dx = end.x - start.x;
  return start.x - left <= EDGE_SWIPE_START_PX && dx >= EDGE_SWIPE_MIN_PX && dx > Math.abs(end.y - start.y);
}
