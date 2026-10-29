import { tabRegistry, type TabRegistry } from './registry';
import type { DynamicTabDef } from './types';
import { DEFAULT_DRAWER_TAB, DRAWER_TAB_STORAGE_KEY } from '../drawer-tabs/drawer-tabs';

export interface TabStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function browserStorage(): TabStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export class TabController {
  stored = $state<string>(DEFAULT_DRAWER_TAB);
  transient = $state<string | null>(null);

  #registry: TabRegistry;
  #storage: () => TabStorage | null;
  #defaultId: string;
  #seen: Set<string> | null = null;

  constructor(registry: TabRegistry, storage: () => TabStorage | null = browserStorage, defaultId = DEFAULT_DRAWER_TAB) {
    this.#registry = registry;
    this.#storage = storage;
    this.#defaultId = defaultId;
  }

  isPresent(def: DynamicTabDef): boolean {
    return def.present ? def.present() : true;
  }

  present(): DynamicTabDef[] {
    return this.#registry.all().filter((def) => this.isPresent(def));
  }

  places(): DynamicTabDef[] {
    return this.#registry.all().filter((def) => def.persist);
  }

  active(): string {
    const id = this.transient;
    const def = id ? this.#registry.get(id) : null;
    return def && this.isPresent(def) ? def.id : this.stored;
  }

  activeDef(): DynamicTabDef | null {
    return this.#registry.get(this.active());
  }

  reload(): void {
    let raw: string | null = null;
    try {
      raw = this.#storage()?.getItem(DRAWER_TAB_STORAGE_KEY) ?? null;
    } catch (err) {
      console.warn('DynamicTabs: storage unreadable, using the default tab', err);
    }
    const def = raw ? this.#registry.get(raw) : null;
    this.stored = def?.persist ? def.id : this.#defaultId;
  }

  select(id: string): boolean {
    const def = this.#registry.get(id);
    if (!def || !this.isPresent(def)) return false;
    if (!def.persist) {
      this.transient = def.id;
      return true;
    }
    this.transient = null;
    this.stored = def.id;
    try {
      this.#storage()?.setItem(DRAWER_TAB_STORAGE_KEY, def.id);
    } catch (err) {
      console.warn('DynamicTabs: could not remember the tab', err);
    }
    return true;
  }

  open(id: string): boolean {
    const def = this.#registry.get(id);
    if (!def) return false;
    if (!this.isPresent(def) && !(def.open?.() ?? false)) return false;
    return this.select(id);
  }

  close(id: string): void {
    const def = this.#registry.get(id);
    if (!def?.close) return;
    def.close();
    if (this.transient === id) this.transient = null;
  }

  leave(): void {
    this.transient = null;
  }

  noteAppearances(now: readonly string[]): void {
    const seen = this.#seen ?? new Set<string>();
    for (const id of now) {
      if (seen.has(id)) continue;
      const def = this.#registry.get(id);
      def?.onAppear?.();
      if (def?.focusOnAppear) this.select(id);
    }
    if (this.transient && !now.includes(this.transient)) this.transient = null;
    this.#seen = new Set(now);
  }
}

export const sidebarTabs = new TabController(tabRegistry);
