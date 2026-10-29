import { rowIdOfSlot } from '../../opscenter/engine/slot-identity';
import { widgetIdOfTab, WIDGET_TAB_PREFIX } from '../../opscenter/engine/widget-tabs';

export type TearOffKind = 'terminal' | 'widget';

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
  const widget = widgetIdOfTab(tab);
  return widget === null ? null : { kind: 'widget', id: widget };
}

export function cellTearOffTarget(slot: string): TearOffTarget | null {
  const widget = widgetIdOfTab(WIDGET_TAB_PREFIX + slot);
  return widget === null ? null : { kind: 'widget', id: widget };
}

export function tearOffCell(slot: string, up: ReleasePoint): boolean {
  return releaseTearOff(window, cellTearOffTarget(slot), up) !== null;
}
