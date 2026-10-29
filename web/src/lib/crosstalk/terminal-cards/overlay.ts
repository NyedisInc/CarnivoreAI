import { mount, unmount } from 'svelte';
import type { TerminalOverlayContext } from '../../../cplugs/sdk/terminal';
import CardStack from './CardStack.svelte';

export function mountCardLayer(context: TerminalOverlayContext): () => void {
  const layer = document.createElement('div');
  layer.className = 'xtalk-layer-host';
  layer.style.display = 'contents';
  context.host.appendChild(layer);
  const handle = mount(CardStack, {
    target: layer,
    props: { sessionId: () => context.controller._sessionId?.() ?? null },
  });
  return () => {
    void unmount(handle, { outro: false });
    layer.remove();
  };
}
