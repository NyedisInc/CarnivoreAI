import { createZone } from '../zone-shell/zone.svelte';
import type { TabRef } from '../zone-shell/zone-types';
import { registerOpener, rightDrawer, selectDrawer, type DrawerKind } from './dock.svelte';

export const RIGHT_DRAWER_ZONE = 'right-drawer';

export const NOTES_HEADER_ID = 'notes-drawer';

const TABS: readonly TabRef[] = [
  { key: 'files', kind: 'panel' },
  { key: 'notes', kind: 'widget' },
];

export const NOTES_ONLY = (tab: TabRef): boolean => tab.key === 'notes';

interface FilesLoader {
  openWhenReady(anchor: HTMLElement | null): Promise<void> | void;
}

function openFiles(): void {
  void (globalThis as { ConfigEditorLoader?: FilesLoader }).ConfigEditorLoader?.openWhenReady(null);
}

registerOpener('files', openFiles);

export const rightDrawerZone = createZone({
  key: RIGHT_DRAWER_ZONE,
  tabs: () => TABS,
  active: () => rightDrawer.kind ?? rightDrawer.last,
  select: (key) => void selectDrawer(key as DrawerKind),
  panel: () => (rightDrawer.kind ? 'open' : 'closed'),
  strip: 'none',
  toolbar: 'header',
  menuHost: 'right-drawer',
  headerId: (tab) => (tab.key === 'notes' ? NOTES_HEADER_ID : `${RIGHT_DRAWER_ZONE}#${tab.key}`),
  seedHeader: (header) => {
    header.drawn = true;
    header.takesBars = true;
  },
});
