import { rowIdOfSlot } from '../../opscenter/engine/slot-identity';
import { widgetIdOfTab, widgetTargetOfTab, WIDGET_TAB_PREFIX } from '../../opscenter/engine/widget-tabs';
import { panels } from '../../opscenter/engine/plugin-kinds';
import { isWidgetId, parseWidgetTarget } from '../../popout/popout';
import { popoutWidgetFor } from '../../plugins/host/popout-widgets';
import { popoutTabOn } from '../dynamic-tabs/popout-tabs';

export type TearOffKind = 'terminal' | 'widget' | 'tab';

const TAB_ID = /^[a-z][a-z0-9-]{0,95}$/;

function canPopOutWidgetSlot(slot: string): boolean {
  if (!isWidgetId(slot)) return false;
  if (slot.startsWith('core.')) return true;
  const { kind } = parseWidgetTarget(slot);
  if (panels().canPopOut?.(kind) === true) return true;
  return popoutWidgetFor(slot)?.enabled === true;
}

export interface TearOffTarget {
  kind: TearOffKind;
  id: string;
}

interface TearOffBridge {
  tearOff?: (kind: TearOffKind, id: string, screenX: number, screenY: number) => Promise<boolean>;
}

export interface ReleasePoint {
  clientX: number;
  clientY: number;
  screenX: number;
  screenY: number;
}

export function tearOffBridge(win: Window): TearOffBridge['tearOff'] | null {
  const bridge = (win as Window & { carnivoreDesktop?: TearOffBridge }).carnivoreDesktop;
  return bridge && typeof bridge.tearOff === 'function' ? bridge.tearOff.bind(bridge) : null;
}

export function pastWindowEdge(win: Window, point: Pick<ReleasePoint, 'clientX' | 'clientY'>): boolean {
  return point.clientX < 0 || point.clientY < 0 || point.clientX >= win.innerWidth || point.clientY >= win.innerHeight;
}

export function releaseTearOff(win: Window, target: TearOffTarget | null, up: ReleasePoint): Promise<boolean> | null {
  const open = tearOffBridge(win);
  if (!open || !target || !pastWindowEdge(win, up)) return null;
  return open(target.kind, target.id, up.screenX, up.screenY).catch((err: unknown) => {
    console.warn('tear off: the app refused', err);
    return false;
  });
}

export function tabTearOffTarget(tab: string): TearOffTarget | null {
  const row = rowIdOfSlot(tab);
  if (row !== null) return { kind: 'terminal', id: String(row) };
  const targetTail = widgetTargetOfTab(tab);
  const widget = widgetIdOfTab(tab);
  if (widget !== null) {
    if (targetTail !== null) {
      const full = `${widget}:${targetTail}`;
      return canPopOutWidgetSlot(full) ? { kind: 'widget', id: full } : null;
    }
    return canPopOutWidgetSlot(widget) ? { kind: 'widget', id: widget } : null;
  }
  if (TAB_ID.test(tab) && popoutTabOn(tab) !== null) {
    return { kind: 'tab', id: tab };
  }
  return null;
}

export function cellTearOffTarget(slot: string): TearOffTarget | null {
  if (isWidgetId(slot)) {
    return canPopOutWidgetSlot(slot) ? { kind: 'widget', id: slot } : null;
  }
  const widget = widgetIdOfTab(WIDGET_TAB_PREFIX + slot);
  return widget !== null && canPopOutWidgetSlot(widget) ? { kind: 'widget', id: widget } : null;
}

export function tearOffCell(slot: string, up: ReleasePoint): boolean {
  return releaseTearOff(window, cellTearOffTarget(slot), up) !== null;
}
