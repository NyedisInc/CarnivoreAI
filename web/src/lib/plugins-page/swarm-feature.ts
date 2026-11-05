import type { ManagerItem } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import type { SwarmSwitchStatus } from '../swarm-switch/control.svelte';

export const SWARM_ITEM_ID = 'switch:swarm';

export function swarmFeatureItem(status: SwarmSwitchStatus | null, t: Translate): ManagerItem | null {
    if (!status) return null;
    return { id: SWARM_ITEM_ID, name: t('features.swarm.name'), brief: t('features.swarm.brief'), enabled: status.enabled, icon: 'bot' };
}
