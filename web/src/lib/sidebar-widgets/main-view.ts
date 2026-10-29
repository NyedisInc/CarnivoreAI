import type { Component } from 'svelte';
import { mountPanel, unmountPanel } from '../mount';
import { surfaceTrackerFor } from '../menu-page/menu-page-surface';
import MainViewHost from './MainViewHost.svelte';

export const MAIN_VIEW_CONTAINER = 'plugin-main-view';

export function showMainView(body: Component, tabId?: string): void {
  mountPanel(MAIN_VIEW_CONTAINER, MainViewHost as unknown as Component<Record<string, unknown>>, { body, tabId });
  surfaceTrackerFor(document)?.start();
}

export function hideMainView(): void {
  unmountPanel(MAIN_VIEW_CONTAINER);
  surfaceTrackerFor(document)?.stop();
}
