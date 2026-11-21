import { openModal } from '../../sdk';
import TaskManagerAskPanel from './TaskManagerAskPanel.svelte';
import { createAsk } from './ask-state.svelte';

const open = new Set<number>();

export async function openAsk(messageId: number): Promise<void> {
  if (open.has(messageId)) return;
  open.add(messageId);
  try {
    await openModal<null, Record<string, unknown>>(TaskManagerAskPanel as never, { messageId });
  } finally {
    open.delete(messageId);
  }
}

export async function dismissAsk(messageId: number): Promise<boolean> {
  const ask = createAsk(messageId);
  await ask.load();
  return ask.dismiss();
}
