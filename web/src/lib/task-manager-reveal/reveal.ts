import { focusTaskManagerItem } from './task-manager-open';
import { t } from '../i18n/index.svelte';
import { revealWish } from '../../cplugs/sdk/task-manager-reveal.svelte';
import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
import { zoneItemKey, type ZoneItem } from '../drawer-zone/zone-model';
import { drawerZone } from '../drawer-zone/zone-store.svelte';
import { showDrawerForPage } from '../drawer/show-drawer';
import { barLead } from '../widget-bars/bar-lead.svelte';
import { widgetBars } from '../widget-bars/bar-settings.svelte';
import { RAIL_EDGES, type RailEdge } from '../session-rail/rail-model';
import { railSlideout } from '../session-rail/slideout.svelte';
import { railStores } from '../session-rail/rail-store.svelte';

export const ALL_WIDGET = 'core.task-manager-all';

const ALL_SELECTOR = '[data-task-manager-all-cell]';
const PROJECT_SELECTOR = '[data-task-manager-cell]';

export type RevealOutcome = 'shown' | 'raised' | 'missing' | 'refused';

export interface RevealResult {
  outcome: RevealOutcome;
  reason: string | null;
}

function drawn(el: Element): boolean {
  return el.isConnected && el.closest('[hidden], [inert]') === null;
}

export function mountedWidget(list: string, doc: Document = document): HTMLElement | null {
  const all = [...doc.querySelectorAll<HTMLElement>(ALL_SELECTOR)].find(drawn);
  if (all) return all;
  return [...doc.querySelectorAll<HTMLElement>(PROJECT_SELECTOR)].find((el) => drawn(el) && el.dataset['taskManagerCell'] === list) ?? null;
}

function drawsAllProjects(item: ZoneItem): boolean {
  return resolvePlacement({ widget: item.widget, view: item.view })?.iconWidget === ALL_WIDGET;
}

export function railHoldingTaskManager(): { edge: RailEdge; key: string } | null {
  for (const edge of RAIL_EDGES) {
    const item = railStores[edge].items.find(drawsAllProjects);
    if (item) return { edge, key: zoneItemKey(item) };
  }
  return null;
}

async function raiseInRail(edge: RailEdge, key: string): Promise<void> {
  if (!widgetBars.view[edge].show) await widgetBars.set(edge, { show: true });
  if (!railSlideout.shown(edge).includes(key)) railSlideout.press(edge, key);
  barLead.take(edge);
}

function focusWidget(el: HTMLElement): void {
  el.scrollIntoView?.({ block: 'nearest' });
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  el.focus({ preventScroll: true });
}

interface BroughtUp {
  outcome: 'shown' | 'raised' | 'missing';
  seen: HTMLElement | null;
}

async function bringUp(list: string): Promise<BroughtUp> {
  const seen = mountedWidget(list);
  const rail = seen ? null : railHoldingTaskManager();
  const inDrawer = !seen && !rail && drawerZone.items.some(drawsAllProjects);
  if (!seen && !rail && !inDrawer) return { outcome: 'missing', seen: null };
  if (rail) await raiseInRail(rail.edge, rail.key);
  else if (inDrawer) showDrawerForPage();
  return { outcome: seen ? 'shown' : 'raised', seen };
}

export async function showTaskManager(): Promise<RevealOutcome> {
  const { outcome, seen } = await bringUp('');
  if (seen) focusWidget(seen);
  return outcome;
}

export async function revealInTaskManager(list: string, id: number): Promise<RevealResult> {
  const { outcome, seen } = await bringUp(list);
  if (outcome === 'missing') return { outcome, reason: null };
  revealWish.id = id;
  const reason = await focusTaskManagerItem(list, id);
  if (reason !== null) {
    revealWish.id = null;
    return { outcome: 'refused', reason };
  }
  if (seen) focusWidget(seen);
  return { outcome, reason: null };
}

export async function openTaskManagerItem(list: string, id: number): Promise<string | null> {
  const result = await revealInTaskManager(list, id);
  return result.outcome === 'missing' ? t('opscenter.cell.task_list.no_tm') : result.reason;
}
