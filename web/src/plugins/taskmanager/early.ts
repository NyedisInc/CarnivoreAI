/* the Task Manager */
import type { CplugWidget } from '../sdk';
import { chatWidgetMeta } from './chat/chat-meta';

export const earlyKinds: readonly { readonly kind: string; readonly meta: CplugWidget['meta'] }[] = [
  { kind: 'huddle.chat', meta: chatWidgetMeta },
];
