import { mountPanel, unmountPanel } from '../lib/mount';
import PhoneTabs from './phone/PhoneTabs.svelte';
import PhoneTabPane from './phone/PhoneTabPane.svelte';
import { terminalLayout } from './engine/layout.svelte';
import { bindPrimary, watchPrimaryBind } from './engine/primary-bind';
import { primarySessionId, primaryTmuxEpoch, primaryTmuxName } from './api/host';
import { noteSurface } from './layouts/page.svelte';

const PANE_ID = 'terminal-phone-pane';

function headerMenu(): { setStripOwnsBar: (on: boolean) => void } | undefined {
  return (globalThis as { HeaderMenu?: { setStripOwnsBar: (on: boolean) => void } }).HeaderMenu;
}

let stopBindWatch: (() => void) | null = null;

export function mountTerminalPhoneTabs(containerId: string): boolean {
  if (!stopBindWatch) stopBindWatch = watchPrimaryBind(terminalLayout);
  bindPrimary(terminalLayout, primarySessionId(), primaryTmuxName(), primaryTmuxEpoch());
  noteSurface('phone', true);
  headerMenu()?.setStripOwnsBar(true);
  const strip = mountPanel(containerId, PhoneTabs) !== null;
  mountPanel(PANE_ID, PhoneTabPane);
  return strip;
}

export function unmountTerminalPhoneTabs(containerId: string): boolean {
  unmountPanel(PANE_ID);
  const gone = unmountPanel(containerId);
  stopBindWatch?.();
  stopBindWatch = null;
  noteSurface('phone', false);
  headerMenu()?.setStripOwnsBar(false);
  return gone;
}
