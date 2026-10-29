import { createOverlayHost } from '../manager-frame/overlay-host';
import { closeMenuPagesExcept } from '../menu-page/menu-page-shell.svelte';
import DocsScreen from './DocsScreen.svelte';
import ChangelogScreen from './ChangelogScreen.svelte';

export const DOCS_SCREEN_CONTAINER = 'docs-screen';
export const CHANGELOG_SCREEN_CONTAINER = 'changelog-screen';

export const DOCS_HASH = '#docs';
export const CHANGELOG_HASH = '#changelog';

const docsHost = createOverlayHost(DOCS_SCREEN_CONTAINER, DocsScreen, DOCS_HASH);
const changelogHost = createOverlayHost(CHANGELOG_SCREEN_CONTAINER, ChangelogScreen, CHANGELOG_HASH);

function openAlone(host: { open(): boolean }): boolean {
    closeMenuPagesExcept(null);
    return host.open();
}

export const openDocsScreen = (): boolean => openAlone(docsHost);
export const openChangelogScreen = (): boolean => openAlone(changelogHost);

export const closeDocsScreen = (): boolean => docsHost.close();
export const closeChangelogScreen = (): boolean => changelogHost.close();

export function wireInfoPageDeepLinks(target?: Window | null): () => void {
    const stops = [docsHost, changelogHost].map((h) => h.wireDeepLink(target));
    return () => stops.forEach((stop) => stop());
}
