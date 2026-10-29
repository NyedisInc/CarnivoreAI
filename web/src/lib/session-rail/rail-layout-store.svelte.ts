import { untrack } from 'svelte';
import { PreferenceField, bridge } from '../zone-shell/preference-field';
import type { ZoneItem } from '../drawer-zone/zone-model';
import type { PlacementOptionValue } from '../../opscenter/widgets/placement-options';
import {
  clampRatio,
  flatItems,
  normalizeRail,
  placeInLayout,
  railToStored,
  removeFromRail,
  setViewInRail,
  setOptionInRail,
  resetOptionsInRail,
  singleSection,
  stepInRail,
  type RailLayout,
  type RailSpot,
} from './rail-sections';

export interface RailStoreOptions {
  field: string;
  defaults: readonly ZoneItem[];
  max: number;
}

function copy(layout: RailLayout): RailLayout {
  return { sections: layout.sections.map((section) => section.map((item) => ({ ...item }))), ratio: layout.ratio };
}

export interface RailWrite {
  field: string;
  value: unknown;
}

export async function saveRailWrites(writes: readonly (RailWrite | null)[]): Promise<void> {
  const staged = writes.filter((write): write is RailWrite => write !== null);
  const found = bridge();
  if (!found || staged.length === 0) return;
  await found.writeMany(staged.map((write) => ({ ...write, localWriter: () => {} })));
}

export class RailStore {
  stored = $state<RailLayout | null>(null);

  readonly #pref: PreferenceField;
  readonly #defaults: readonly ZoneItem[];
  readonly #max: number;

  constructor(options: RailStoreOptions) {
    this.#defaults = options.defaults;
    this.#max = options.max;
    this.#pref = new PreferenceField(options.field, (value) => {
      this.stored = normalizeRail(value, this.#max);
    });
  }

  get layout(): RailLayout {
    return this.stored ?? singleSection(this.#defaults);
  }

  get items(): ZoneItem[] {
    return flatItems(this.layout);
  }

  get sections(): ZoneItem[][] {
    return this.layout.sections;
  }

  get ratio(): number {
    return this.layout.ratio;
  }

  get split(): boolean {
    return this.layout.sections.length > 1;
  }

  start(target: Window | null = typeof window !== 'undefined' ? window : null): void {
    this.#pref.start(target);
  }

  reload(): void {
    this.#pref.reload();
  }

  async commit(next: RailLayout): Promise<void> {
    this.stored = copy(next);
    await this.#pref.write(railToStored(next));
  }

  #commitIfChanged(next: RailLayout): boolean {
    const current = untrack(() => this.layout);
    if (JSON.stringify(railToStored(next)) === JSON.stringify(railToStored(current))) return false;
    void this.commit(next);
    return true;
  }

  #stage(next: RailLayout): RailWrite | null {
    const current = untrack(() => this.layout);
    if (JSON.stringify(railToStored(next)) === JSON.stringify(railToStored(current))) return null;
    this.stored = copy(next);
    return { field: this.#pref.field, value: railToStored(next) };
  }

  stagePlace(spot: RailSpot, widget: string, target?: string, instance?: string | null, carried?: ZoneItem): RailWrite | null {
    return this.#stage(placeInLayout(untrack(() => this.layout), spot, widget, target, this.#max, instance, carried));
  }

  stageRemove(key: string): RailWrite | null {
    return this.#stage(removeFromRail(untrack(() => this.layout), key));
  }

  place(spot: RailSpot, widget: string, target?: string, instance?: string | null, carried?: ZoneItem): boolean {
    return this.#commitIfChanged(placeInLayout(untrack(() => this.layout), spot, widget, target, this.#max, instance, carried));
  }

  remove(key: string): boolean {
    return this.#commitIfChanged(removeFromRail(untrack(() => this.layout), key));
  }

  step(key: string, direction: -1 | 1): void {
    this.#commitIfChanged(stepInRail(untrack(() => this.layout), key, direction));
  }

  setView(key: string, view: string): boolean {
    return this.#commitIfChanged(setViewInRail(untrack(() => this.layout), key, view));
  }

  setOption(key: string, option: string, value: PlacementOptionValue | null): boolean {
    return this.#commitIfChanged(setOptionInRail(untrack(() => this.layout), key, option, value));
  }

  resetOptions(key: string): boolean {
    return this.#commitIfChanged(resetOptionsInRail(untrack(() => this.layout), key));
  }

  previewRatio(ratio: number): number {
    const current = untrack(() => this.layout);
    const next = clampRatio(ratio);
    if (current.sections.length > 1) this.stored = { ...copy(current), ratio: next };
    return next;
  }

  saveRatio(): void {
    const current = untrack(() => this.layout);
    if (current.sections.length > 1) void this.commit(current);
  }
}
