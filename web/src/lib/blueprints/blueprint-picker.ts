import { mountInto } from '../mount';
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
    let stop: (() => void) | null = null;
    const close = (): void => {
        stop?.();
        if (host.parentNode) host.parentNode.removeChild(host);
    };
    stop = mountInto(host, CascadeMenu, { root, anchor, label: t('blueprint.title'), onClose: close });
}
