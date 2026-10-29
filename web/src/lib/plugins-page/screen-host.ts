import { createOverlayHost } from '../manager-frame/overlay-host';
import PluginsScreen from './PluginsScreen.svelte';
import { pluginSettingsHash } from './plugin-settings-link';

export const PLUGINS_SCREEN_CONTAINER = 'plugins-screen';

export const PLUGINS_HASH = '#plugins';

export const LEGACY_TASK_MANAGER_SETTINGS_HASHES: readonly string[] = ['#swarm-settings', '#interactive-todo'];

const host = createOverlayHost(PLUGINS_SCREEN_CONTAINER, PluginsScreen, PLUGINS_HASH, { aliases: LEGACY_TASK_MANAGER_SETTINGS_HASHES });

export const openPluginsScreen = (): boolean => host.open();

export const openPluginSettings = (cplugId: string): boolean => host.open({ plugin: cplugId, settings: true });

export { pluginSettingsHash };

export const closePluginsScreen = (): boolean => host.close();

export const wirePluginsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
