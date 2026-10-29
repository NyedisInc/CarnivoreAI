
import { untrack } from 'svelte';
import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
import { fullIndex } from './drawn-index';
import { PreferenceField } from '../zone-shell/preference-field';
import {
  DEFAULT_ZONE_ITEMS,
  MAX_ZONE_ITEMS,
  ZONE_FIELD,
  addItem,
  moveItem,
  normalizeZone,
  setItemView,
  setItemOption,
  resetItemOptions,
  removeItem,
  setItemLook,
  stepItem,
  zoneItemKey,
  toStored,
  type ZoneItem,
} from './zone-model';
import type { WidgetLook } from '../../opscenter/widgets/types';
import {
  addPlacement,
  derivedGlance,
  glanceToStored,
  movePlacement,
  normalizeGlance,
  removePlacement,
  setPlacementOption,
  setPlacementWidget,
  type GlancePlacement,
  type PlacementOptionValue,
} from './glance-model';

export interface ZoneStoreOptions {
  field: string;
  defaults: readonly ZoneItem[];
  max?: number;
  drawnOnly?: boolean;
}

export class DrawerZoneStore {
  stored = $state<ZoneItem[] | null>(null);

  glanceStored = $state<GlancePlacement[] | null>(null);

  readonly #pref: PreferenceField;
  readonly #defaults: readonly ZoneItem[];
  readonly #max: number;
  readonly #drawnOnly: boolean;
  readonly #field: string;

  constructor(options: ZoneStoreOptions = { field: ZONE_FIELD, defaults: DEFAULT_ZONE_ITEMS, drawnOnly: true }) {
    this.#drawnOnly = options.drawnOnly === true;
    this.#defaults = options.defaults;
    this.#max = options.max ?? MAX_ZONE_ITEMS;
    this.#field = options.field;
    this.#pref = new PreferenceField(options.field, (value) => {
      this.stored = normalizeZone(value, this.#max);
      this.glanceStored = normalizeGlance(value);
    });
  }

  get items(): ZoneItem[] {
    return this.stored ?? this.#defaults.map((item) => ({ ...item }));
  }

  /* the glance area */
  get glance(): GlancePlacement[] {
    return this.glanceStored ?? derivedGlance(this.items);
  }

  #drawnItem = (item: ZoneItem): boolean => !!resolvePlacement({ widget: item.widget, view: item.view, target: item.target ?? null, instance: item.instance ?? null });

  #drawnGlance = (p: GlancePlacement): boolean => !!resolvePlacement({ widget: p.widget });

  #toStored<T>(list: readonly T[], isDrawn: (item: T) => boolean, index: number): number {
    return this.#drawnOnly ? fullIndex(list, isDrawn, index) : index;
  }

  start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
    this.#pref.start(target);
  }

  reload(): void {
    this.#pref.reload();
  }

  async commit(next: readonly ZoneItem[], glance: readonly GlancePlacement[] | null = untrack(() => this.glanceStored)): Promise<void> {
    this.stored = next.map((item) => ({ ...item }));
    this.glanceStored = glance ? glance.map((p) => ({ ...p, options: { ...p.options } })) : null;
    try {
      await this.#pref.write(glance ? { ...toStored(next), glance: glanceToStored(glance) } : toStored(next));
    } catch (err) {
      console.warn(`DrawerZoneStore: could not save the ${this.#field} field:`, err);
      this.#pref.reload();
    }
  }

  #commitGlance(next: readonly GlancePlacement[]): void {
    void this.commit(untrack(() => this.items), next);
  }

  addGlance(widget: string, repeatable: boolean, index?: number, options: Readonly<Record<string, PlacementOptionValue>> = {}): string | null {
    const current = untrack(() => this.glance);
    const next = addPlacement(current, widget, repeatable, index === undefined ? undefined : this.#toStored(current, this.#drawnGlance, index), options);
    if (next.length === current.length) return null;
    this.#commitGlance(next);
    const before = new Set(current.map((p) => p.id));
    return next.find((p) => !before.has(p.id))?.id ?? null;
  }

  removeGlance(id: string): boolean {
    const current = untrack(() => this.glance);
    const next = removePlacement(current, id);
    if (next.length === current.length) return false;
    this.#commitGlance(next);
    return true;
  }

  moveGlance(id: string, index: number): void {
    const current = untrack(() => this.glance);
    this.#commitGlance(movePlacement(current, id, this.#toStored(current.filter((p) => p.id !== id), this.#drawnGlance, index)));
  }

  setGlanceWidget(id: string, widget: string): void {
    this.#commitGlance(setPlacementWidget(untrack(() => this.glance), id, widget));
  }

  setGlanceOption(id: string, key: string, value: PlacementOptionValue | null): void {
    this.#commitGlance(setPlacementOption(untrack(() => this.glance), id, key, value));
  }

  add(widget: string, index?: number, target?: string): boolean {
    const current = untrack(() => this.items);
    const next = addItem(current, widget, index === undefined ? undefined : this.#toStored(current, this.#drawnItem, index), target, this.#max);
    if (next.length === current.length) return false;
    void this.commit(next);
    return true;
  }

  remove(key: string): boolean {
    const current = untrack(() => this.items);
    const next = removeItem(current, key);
    if (next.length === current.length) return false;
    void this.commit(next);
    return true;
  }

  move(key: string, index: number): void {
    const current = untrack(() => this.items);
    void this.commit(moveItem(current, key, this.#toStored(current.filter((item) => zoneItemKey(item) !== key), this.#drawnItem, index)));
  }

  step(key: string, direction: -1 | 1): void {
    const current = untrack(() => this.items);
    if (!this.#drawnOnly) {
      void this.commit(stepItem(current, key, direction));
      return;
    }
    const at = current.filter(this.#drawnItem).findIndex((item) => zoneItemKey(item) === key);
    const to = at + direction;
    if (at < 0 || to < 0 || to >= current.filter(this.#drawnItem).length) return;
    this.move(key, to);
  }

  setLook(key: string, look: WidgetLook): void {
    void this.commit(setItemLook(untrack(() => this.items), key, look));
  }

  setView(key: string, view: string): void {
    void this.commit(setItemView(untrack(() => this.items), key, view));
  }

  setOption(key: string, option: string, value: PlacementOptionValue | null): void {
    void this.commit(setItemOption(untrack(() => this.items), key, option, value));
  }

  resetOptions(key: string): void {
    void this.commit(resetItemOptions(untrack(() => this.items), key));
  }
}

export const drawerZone = new DrawerZoneStore();
