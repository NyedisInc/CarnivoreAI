import type { ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import type { SwarmSwitchStatus } from '../swarm-switch/control.svelte';
import { CPLUG_ITEM_PREFIX } from './cplugs-adapter';

export const SWARM_ITEM_ID = 'switch:swarm';

interface SwarmHostManifest {
    readonly id?: string;
    readonly permissions?: { readonly write?: readonly string[]; readonly app?: readonly string[] };
    readonly ui?: { readonly plugins?: readonly string[] };
    readonly surfaces?: { readonly plugins?: readonly string[] };
}

const MANIFESTS = import.meta.glob<SwarmHostManifest>(
    '../../../../src/plugins/*/carnivore.toml',
    { eager: true, import: 'default' },
);

function findSwarmSettingsHostId(): string | null {
    for (const manifest of Object.values(MANIFESTS)) {
        const id = manifest?.id;
        if (!id) continue;
        const perms = manifest.permissions?.write ?? manifest.permissions?.app ?? [];
        const panels = manifest.ui?.plugins ?? manifest.surfaces?.plugins ?? [];
        if (perms.includes('swarm') && panels.includes('settings-panel')) {
            return `${CPLUG_ITEM_PREFIX}${id}`;
        }
    }
    return null;
}

const SWARM_SETTINGS_HOST_ID = findSwarmSettingsHostId();

export function swarmFeatureItem(status: SwarmSwitchStatus | null, t: Translate): ManagerItem | null {
    if (!status) return null;
    return { id: SWARM_ITEM_ID, name: t('features.swarm.name'), brief: t('features.swarm.brief'), enabled: status.enabled, icon: 'bot' };
}

export function resolveSwarmSelectionTarget(id: string | null, items: readonly { readonly id: string }[]): { readonly target: string | null } | null {
    if (id !== SWARM_ITEM_ID) return { target: id };
    if (!SWARM_SETTINGS_HOST_ID) return null;
    return items.some((row) => row.id === SWARM_SETTINGS_HOST_ID) ? { target: SWARM_SETTINGS_HOST_ID } : null;
}
