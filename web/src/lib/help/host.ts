import { mountPanel, unmountPanel } from '../mount';
import HelpReleases from './HelpReleases.svelte';
import HelpFeatures from './HelpFeatures.svelte';
import type { Component } from 'svelte';

export const HELP_RELEASES_CONTAINER = 'sidebar-help-releases';

export const HELP_FEATURES_CONTAINER = 'sidebar-help-features';

const HELP_RELEASES_PANEL = HelpReleases as unknown as Component<
    Record<string, never>,
    Record<string, unknown>
>;

const HELP_FEATURES_PANEL = HelpFeatures as unknown as Component<
    Record<string, never>,
    Record<string, unknown>
>;

export function mountHelpReleases(): Record<string, unknown> | null {
    return mountPanel(HELP_RELEASES_CONTAINER, HELP_RELEASES_PANEL, {});
}

export function unmountHelpReleases(): boolean {
    return unmountPanel(HELP_RELEASES_CONTAINER);
}

export function mountHelpFeatures(): Record<string, unknown> | null {
    return mountPanel(HELP_FEATURES_CONTAINER, HELP_FEATURES_PANEL, {});
}

export function unmountHelpFeatures(): boolean {
    return unmountPanel(HELP_FEATURES_CONTAINER);
}
