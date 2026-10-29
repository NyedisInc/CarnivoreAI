
export const SIDEBAR_WIDTHS = ['min', 'default', 'wide', 'max'] as const;
export type SidebarWidth = (typeof SIDEBAR_WIDTHS)[number];

export const SIDEBAR_AREAS = ['closed', 'glance', 'full'] as const;
export type SidebarArea = (typeof SIDEBAR_AREAS)[number];

export const SIDEBAR_DENSITIES = ['compact', 'cozy', 'detailed'] as const;
export type SidebarDensity = (typeof SIDEBAR_DENSITIES)[number];

export interface SidebarView {
  width: SidebarWidth;
  folded: boolean;
  area: SidebarArea;
  density: SidebarDensity;
}

export const DEFAULT_SIDEBAR_VIEW: Readonly<SidebarView> = Object.freeze({ width: 'default', folded: false, area: 'full', density: 'compact' });

export function widthPx(width: SidebarWidth, limits: { min: number; normal: number; max: number }): number {
  if (width === 'min') return limits.min;
  if (width === 'default') return limits.normal;
  if (width === 'max') return limits.max;
  return Math.round((limits.normal + limits.max) / 2);
}

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return (allowed as readonly string[]).includes(value ?? '') ? (value as T) : fallback;
}

export function viewFromQuery(params: URLSearchParams): SidebarView {
  return {
    width: pick(params.get('width'), SIDEBAR_WIDTHS, DEFAULT_SIDEBAR_VIEW.width),
    folded: params.get('folded') === '1',
    area: pick(params.get('area'), SIDEBAR_AREAS, DEFAULT_SIDEBAR_VIEW.area),
    density: pick(params.get('density'), SIDEBAR_DENSITIES, DEFAULT_SIDEBAR_VIEW.density),
  };
}

export function viewToQuery(view: SidebarView): Record<string, string> {
  return { width: view.width, folded: view.folded ? '1' : '0', area: view.area, density: view.density };
}
