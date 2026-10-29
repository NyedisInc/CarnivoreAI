import { drawerEnv } from '../../lib/drawer/env';
import { readKey, writeKey } from '../../lib/drawer/storage';
import { viewClass, type ViewClass } from '../../lib/drawer/view-class';
import { DEFAULT_DRAWER_VIEW, isDrawerViewMode, type DrawerViewMode } from './drawer-view';
import type { WidgetType } from '../widgets/types';

export const VIEW_FIELD = 'widget_drawer_view';
export const VIEW_FIELD_MOBILE = 'widget_drawer_view_mobile';
export const VIEW_STORAGE_KEY = 'carnivore.widget_drawer.view';
export const VIEW_STORAGE_KEY_MOBILE = 'carnivore.widget_drawer.view.mobile';

interface Bridge {
  read?(field: string, fallback: () => string | null): unknown;
  write?(field: string, value: string, local: () => void): Promise<unknown>;
}

function bridge(): Bridge | undefined {
  return (drawerEnv() as { PreferenceBridge?: Bridge }).PreferenceBridge;
}

function readLocal(key: string): DrawerViewMode | null {
  try {
    const raw = readKey(key);
    return isDrawerViewMode(raw) ? raw : null;
  } catch {
    return null;
  }
}

function own(cls: ViewClass): DrawerViewMode | null {
  const field = cls === 'mobile' ? VIEW_FIELD_MOBILE : VIEW_FIELD;
  const key = cls === 'mobile' ? VIEW_STORAGE_KEY_MOBILE : VIEW_STORAGE_KEY;
  const b = bridge();
  const value = b && typeof b.read === 'function' ? b.read(field, () => readLocal(key)) : readLocal(key);
  return isDrawerViewMode(value) ? value : null;
}

export function resolveView(cls: ViewClass): DrawerViewMode {
  return own(cls) ?? (cls === 'mobile' ? own('desktop') : null) ?? DEFAULT_DRAWER_VIEW;
}

class WidgetDrawerView {
  #mode = $state<DrawerViewMode | null>(null);
  folded = $state<ReadonlySet<WidgetType>>(new Set());

  get mode(): DrawerViewMode {
    if (this.#mode === null) this.#mode = resolveView(viewClass());
    return this.#mode;
  }

  setMode(next: DrawerViewMode): boolean {
    if (next === this.mode) return false;
    this.#mode = next;
    const cls = viewClass();
    const key = cls === 'mobile' ? VIEW_STORAGE_KEY_MOBILE : VIEW_STORAGE_KEY;
    const writeLocal = (): void => {
      try {
        writeKey(key, next);
      } catch (error) {
        console.warn('[widget-drawer] could not keep the view in this browser', error);
      }
    };
    const b = bridge();
    if (b && typeof b.write === 'function') {
      b.write(cls === 'mobile' ? VIEW_FIELD_MOBILE : VIEW_FIELD, next, writeLocal).catch((error: unknown) => {
        console.warn('[widget-drawer] could not share the view', error);
      });
    } else {
      writeLocal();
    }
    return true;
  }

  reset(): void {
    this.#mode = null;
    this.folded = new Set();
  }
}

export const widgetDrawerView = new WidgetDrawerView();
