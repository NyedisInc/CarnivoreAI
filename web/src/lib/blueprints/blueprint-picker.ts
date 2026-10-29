import { mount, unmount } from 'svelte';
import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
import { buildBlueprintChildren } from '../../opscenter/shell/tab-menu';
import { t } from '../i18n/index.svelte';
import { openModal } from '../modal';
import LaunchModal from './LaunchModal.svelte';
import { listBlueprints } from './api';
import type { Blueprint } from './types';
import { openBlueprintsScreen } from './screen-host';

function launchOne(blueprint: Blueprint): void {
    void openModal(LaunchModal, { uuid: blueprint.blueprint_uuid, name: blueprint.name });
}

export async function openBlueprintPicker(anchor: HTMLElement): Promise<void> {
    let list;
    try {
        list = await listBlueprints();
    } catch {
        openBlueprintsScreen();
        return;
    }
    if (list.status !== 'ok') {
        openBlueprintsScreen();
        return;
    }
    const root = buildBlueprintChildren(list.blueprints, launchOne, openBlueprintsScreen);

    const host = document.createElement('div');
    document.body.appendChild(host);
    let instance: Record<string, unknown> | null = null;
    const close = (): void => {
        if (instance) unmount(instance, { outro: false });
        if (host.parentNode) host.parentNode.removeChild(host);
    };
    instance = mount(CascadeMenu, {
        target: host,
        props: { root, anchor, label: t('blueprint.title'), onClose: close },
    }) as Record<string, unknown>;
}
