import { widgetSetting, itemSettings } from '../item-settings/store.svelte';
import { writeItem } from '../item-settings/api';

export const FILES_WIDGET_ID = 'core.files';

export type TopFolder = 'global' | 'project';

export interface RootPrefs {
  showGlobal: boolean;
  topFolder: TopFolder;
}

export function filesRootPrefs(): RootPrefs {
  return {
    showGlobal: widgetSetting(FILES_WIDGET_ID, 'showGlobalFolder') !== false,
    topFolder: widgetSetting(FILES_WIDGET_ID, 'topFolder') === 'project' ? 'project' : 'global',
  };
}

interface RootsModule {
  setPrefs(next: RootPrefs): boolean;
}

export function publishRootPrefs(prefs: RootPrefs): boolean {
  const roots = (globalThis as { ConfigEditorRoots?: RootsModule }).ConfigEditorRoots;
  return roots ? roots.setPrefs(prefs) : false;
}

export async function writeRootPrefs(change: { showGlobalFolder?: boolean; topFolder?: TopFolder }): Promise<void> {
  await writeItem('widget', FILES_WIDGET_ID, { values: change });
  await itemSettings.refresh(true);
}
