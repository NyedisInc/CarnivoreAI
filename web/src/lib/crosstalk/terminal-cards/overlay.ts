import { mountInto } from '../../mount';
import type { TerminalOverlayContext } from '../../../cplugs/sdk/terminal';
import CardStack from './CardStack.svelte';

export function mountCardLayer(context: TerminalOverlayContext): () => void {
  const layer = document.createElement('div');
  layer.className = 'xtalk-layer-host';
  layer.style.display = 'contents';
  context.host.appendChild(layer);
  const stop = mountInto(layer, CardStack, { sessionId: () => context.controller._sessionId?.() ?? null });
  return () => {
    stop();
    layer.remove();
  };
}
