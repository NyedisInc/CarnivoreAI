import { WIDGET_AREA_STATES, type DynamicTabDef } from './types';

export type TabRefusal = 'id' | 'duplicate-id' | 'label-key' | 'icon' | 'order' | 'duplicate-order' | 'body' | 'widget-area' | 'popout';

export interface TabRegistry {
  register(def: DynamicTabDef): TabRefusal | null;
  all(): readonly DynamicTabDef[];
  get(id: string): DynamicTabDef | null;
}

const ID_RE = /^[a-z][a-z0-9-]*$/;

export function refusalOf(def: DynamicTabDef, taken: readonly DynamicTabDef[]): TabRefusal | null {
  if (!def || typeof def.id !== 'string' || !ID_RE.test(def.id)) return 'id';
  if (taken.some((t) => t.id === def.id)) return 'duplicate-id';
  if (typeof def.labelKey !== 'string' || !def.labelKey) return 'label-key';
  if (typeof def.icon !== 'string' || !def.icon) return 'icon';
  if (typeof def.order !== 'number' || !Number.isFinite(def.order)) return 'order';
  if (taken.some((t) => t.order === def.order)) return 'duplicate-order';
  const body = def.body as Record<string, unknown> | undefined;
  const hasContainers = !!body && Array.isArray(body.containers) && body.containers.length > 0;
  const hasComponent = !!body && typeof body.component === 'function';
  if (hasContainers === hasComponent) return 'body';
  if (!(WIDGET_AREA_STATES as readonly string[]).includes(def.widgetArea)) return 'widget-area';
  // pop-out window
  if (def.popout && (!hasComponent || !(body as { titleKey?: unknown }).titleKey)) return 'popout';
  return null;
}

export function createTabRegistry(): TabRegistry {
  const defs: DynamicTabDef[] = [];
  return {
    register(def) {
      const refusal = refusalOf(def, defs);
      if (refusal) {
        console.warn('DynamicTabs: refused a tab', { id: (def as { id?: unknown })?.id, refusal });
        return refusal;
      }
      defs.push(def);
      defs.sort((a, b) => a.order - b.order);
      return null;
    },
    all: () => defs,
    get: (id) => defs.find((d) => d.id === id) ?? null,
  };
}

export const tabRegistry: TabRegistry = createTabRegistry();

export function registerTab(def: DynamicTabDef): TabRefusal | null {
  return tabRegistry.register(def);
}
