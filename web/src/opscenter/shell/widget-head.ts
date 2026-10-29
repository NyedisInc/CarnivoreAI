
export const HEAD_ROW_PX = 31;

export const PHONE_HEAD_PX = 44;

export type HeadPart =
  | { kind: 'group'; at: number }
  | { kind: 'sep' }
  | { kind: 'close' };

export function headParts(groups: readonly boolean[], closable: boolean): HeadPart[] {
  const out: HeadPart[] = [];
  groups.forEach((filled, at) => {
    if (!filled) return;
    if (out.length) out.push({ kind: 'sep' });
    out.push({ kind: 'group', at });
  });
  if (closable) {
    if (out.length) out.push({ kind: 'sep' });
    out.push({ kind: 'close' });
  }
  return out;
}

/* pop-out window */
export type HeadSurface = 'grid' | 'drawer' | 'rail' | 'popout';

export const HEADER_OPTION = 'show_header';

export const RAIL_HEADER_ON: ReadonlySet<string> = new Set(['core.task-list']);

export function placementHeaderShown(surface: 'drawer' | 'rail', options: Readonly<Record<string, unknown>> | undefined, widgetId?: string): boolean {
  const stored = options?.[HEADER_OPTION];
  if (typeof stored !== 'boolean' && surface === 'rail' && widgetId !== undefined && RAIL_HEADER_ON.has(widgetId)) return true;
  return headerShown(surface, typeof stored === 'boolean' ? stored : undefined);
}

export interface MenuSlot {
  anchor: HTMLElement | null;
  close: () => void;
}

const HEADER_DEFAULT: Readonly<Record<HeadSurface, boolean>> = { grid: true, drawer: true, popout: true, rail: false };

export function headerShown(surface: HeadSurface, stored: boolean | undefined): boolean {
  return stored ?? HEADER_DEFAULT[surface];
}
