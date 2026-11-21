import type { CplugWidget } from './sdk';
import { chatWidgetMeta } from './huddle/chat/chat-meta';

export interface EarlyKind {
  kind: string;
  meta: CplugWidget['meta'];
}

export const EARLY_KINDS: readonly EarlyKind[] = [{ kind: 'huddle.chat', meta: chatWidgetMeta }];
