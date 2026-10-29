import type { OutboxEntry } from './outbox-model';
import { isStored, listEntries, subscribe } from './outbox-store';

export const outboxView: { entries: OutboxEntry[]; stored: boolean } = $state({ entries: listEntries(), stored: isStored() });

subscribe(() => {
  outboxView.entries = listEntries();
  outboxView.stored = isStored();
});
