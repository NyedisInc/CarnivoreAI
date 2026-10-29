/*  hidden  */
import { inputFocus } from '../../lib/input-focus.svelte';
import type { TabPane } from '../../shell/frame-header.svelte';

interface SizeVote {
  setTabHidden(client: unknown, hidden: boolean, doc?: Document): void;
}

function vote(): SizeVote | undefined {
  return (globalThis as { TerminalSizeVote?: SizeVote }).TerminalSizeVote;
}

/*  hidden  */
export function followTab(
  client: unknown,
  slot: string,
  pane: Pick<TabPane, 'active'> | undefined,
  covered = false,
): void {
  const hidden = (pane ? !pane.active : false) || covered;
  vote()?.setTabHidden(client, hidden, globalThis.document);
  if (hidden) inputFocus.release(slot);
}

export function rejoinTab(client: unknown): void {
  vote()?.setTabHidden(client, false, globalThis.document);
}
