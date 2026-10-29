import { createFrameHeader, type FrameHeader } from '../../opscenter/shell/frame-header.svelte';
import { documentHidden, observeOnScreen } from './zone-onscreen.svelte';
import { tabVisibility } from './zone-visibility';
import type { TabRef, ZoneMenuAnchor, ZoneSpec, ZoneVisibility } from './zone-types';

export interface Zone {
  readonly spec: ZoneSpec;
  readonly tabs: readonly TabRef[];
  readonly active: TabRef | null;
  /*  hidden  */
  visibility(tabKey: string): ZoneVisibility;
  headerFor(tabKey: string): FrameHeader;
  release(tabKey: string): void;
  headerIdOf(tab: TabRef): string;
  readonly toolbar: FrameHeader | null;
  setOnScreen(tabKey: string, onScreen: boolean): void;
  watch(tabKey: string): (el: Element) => () => void;
  openMenu(tabKey: string, anchor: ZoneMenuAnchor): boolean;
}

export function createZone(spec: ZoneSpec): Zone {
  const headers = new Map<string, FrameHeader>();
  const offScreen = $state<Record<string, boolean>>({});

  const tabOf = (key: string): TabRef | undefined => spec.tabs().find((one) => one.key === key);
  const headerIdOf = (tab: TabRef): string => spec.headerId?.(tab) ?? `${spec.key}#${tab.key}`;
  const setOnScreen = (tabKey: string, onScreen: boolean): void => {
    offScreen[tabKey] = !onScreen;
  };

  return {
    spec,
    get tabs() {
      return spec.tabs();
    },
    get active() {
      const key = spec.active();
      return key === null ? null : (tabOf(key) ?? null);
    },
    visibility(tabKey) {
      return tabVisibility({
        unseen: tabOf(tabKey)?.unseen === true,
        panel: spec.panel(),
        active: spec.active() === tabKey,
        docHidden: documentHidden(),
        onScreen: offScreen[tabKey] !== true,
      });
    },
    headerFor(tabKey) {
      let header = headers.get(tabKey);
      if (!header) {
        const tab = tabOf(tabKey);
        header = createFrameHeader(tab ? headerIdOf(tab) : `${spec.key}#${tabKey}`);
        spec.seedHeader?.(header);
        headers.set(tabKey, header);
      }
      return header;
    },
    headerIdOf,
    release(tabKey) {
      headers.delete(tabKey);
    },
    get toolbar() {
      const key = spec.active();
      return key === null ? null : this.headerFor(key);
    },
    setOnScreen,
    watch(tabKey) {
      return (el) => observeOnScreen(el, (on) => setOnScreen(tabKey, on));
    },
    openMenu(tabKey, anchor) {
      const tab = tabOf(tabKey);
      if (!tab || !spec.openMenu) return false;
      return spec.openMenu(tab, anchor) !== false;
    },
  };
}
