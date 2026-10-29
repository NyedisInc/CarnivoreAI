import { createOverlayHost } from '../manager-frame/overlay-host';
import { closeMenuPagesExcept } from '../menu-page/menu-page-shell.svelte';
import { registerCplugPage } from '../../cplugs/sdk/pages';
import { SWARM_HASH, SWARM_PAGE } from '../../cplugs/huddle/swarm/swarm-page';
import SwarmScreen from './SwarmScreen.svelte';

export const HUDDLE_SWARM_CONTAINER = 'huddle-swarm-screen';

const host = createOverlayHost(HUDDLE_SWARM_CONTAINER, SwarmScreen, SWARM_HASH);

export function openHuddleSwarmScreen(): boolean {
  closeMenuPagesExcept(null);
  return host.open();
}

export const closeHuddleSwarmScreen = (): boolean => host.close();

export const wireHuddleSwarmDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);

registerCplugPage(SWARM_PAGE, openHuddleSwarmScreen);
