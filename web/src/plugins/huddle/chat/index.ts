import type { CplugWidget } from '../../sdk';
import ChatWidgetHost from './ChatWidgetHost.svelte';
import { chatWidgetMeta } from './chat-meta';

export const chatWidget: CplugWidget = {
  name: 'chat',
  component: ChatWidgetHost,
  meta: chatWidgetMeta,
  extras: { category: 'tools', type: 'feed', capabilities: ['server-write', 'navigate'] },
};
