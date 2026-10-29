import { createOverlayHost } from '../manager-frame/overlay-host';
import { closeMenuPagesExcept } from '../menu-page/menu-page-shell.svelte';
import { registerCplugPage } from '../../cplugs/sdk/pages';
import { AGENT_HASH, AGENT_PAGE } from '../../cplugs/huddle/agents/agent-page.svelte';
import HuddleAgentScreen from './HuddleAgentScreen.svelte';
import { openAgentDrawerHost } from './drawer-host';

export const HUDDLE_AGENT_CONTAINER = 'huddle-agent-screen';

const host = createOverlayHost(HUDDLE_AGENT_CONTAINER, HuddleAgentScreen, AGENT_HASH);

export function openHuddleAgentScreen(): boolean {
  closeMenuPagesExcept(null);
  return host.open();
}

export const closeHuddleAgentScreen = (): boolean => host.close();

export const wireHuddleAgentDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);

registerCplugPage(AGENT_PAGE, openAgentDrawerHost);
