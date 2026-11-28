/* the Task Manager */
import { createOverlayHost } from '../manager-frame/overlay-host';
import { registerCplugPage } from '../../plugins/sdk/pages';
import { AGENT_HASH, AGENT_PAGE } from '../../plugins/taskmanager/agents/agent-page.svelte';
import { openAgentDrawerHost } from './drawer-host';

export const HUDDLE_AGENT_CONTAINER = 'huddle-agent-screen';

const host = createOverlayHost(HUDDLE_AGENT_CONTAINER, { load: () => import('./HuddleAgentScreen.svelte') }, AGENT_HASH);

export const closeHuddleAgentScreen = (): boolean => host.close();

export const wireHuddleAgentDeepLink = (target?: Window | null): (() => void) => host.wireDeepLink(target);

registerCplugPage(AGENT_PAGE, openAgentDrawerHost);
