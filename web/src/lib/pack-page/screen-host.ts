import { createOverlayHost } from '../manager-frame/overlay-host';
import PackScreen from './PackScreen.svelte';
import type { PackTab } from './pack-hash';

export const HOSTS_SCREEN_CONTAINER = 'hosts-screen';

export const PACK_HASH = '#pack';

const host = createOverlayHost(HOSTS_SCREEN_CONTAINER, PackScreen, PACK_HASH, { aliases: ['#hosts', '#ssh'] });

export const openHostsScreen = (tab?: PackTab): boolean => host.open(tab ? { tab } : undefined);

export const closeHostsScreen = (): boolean => host.close();

export const wireHostsDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);
