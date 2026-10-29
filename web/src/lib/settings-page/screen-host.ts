import { createOverlayHost } from '../manager-frame/overlay-host';
import SettingsScreen from './SettingsScreen.svelte';
import type { SectionId } from './settings-registry';
import { settingsFragment, settingsPluginOf, settingsTabOf, writeSettingsFragment } from './settings-hash';
import { registerSettingsOpener } from './settings-navigate';

export const SETTINGS_SCREEN_CONTAINER = 'settings-screen';

export const SETTINGS_HASH = '#settings';

export const SETTINGS_ALIASES = ['#wrappers', '#launch-profiles', '#shortcuts'] as const;

const host = createOverlayHost(SETTINGS_SCREEN_CONTAINER, SettingsScreen, SETTINGS_HASH, { aliases: SETTINGS_ALIASES });

export const openSettingsScreen = (): boolean => host.open();

export const openSettingsSection = (section: SectionId, tab?: string): boolean => {
    writeSettingsFragment(settingsFragment(section, tab));
    return host.open();
};

export const openSettingsLink = (href: string): boolean => {
    if (!(settingsTabOf(href) || settingsPluginOf(href)) || typeof window === 'undefined') return false;
    writeSettingsFragment(href);
    return host.open();
};

registerSettingsOpener(openSettingsLink);

export const closeSettingsScreen = (): boolean => host.close();

export const unmountSettingsScreen = (): boolean => host.unmount();

export const isSettingsHash = (hash: string | null | undefined): boolean => host.isHash(hash);

export const wireSettingsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
