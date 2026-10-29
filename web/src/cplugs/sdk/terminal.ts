export { registerTerminalOverlay } from '../../opscenter/cells/terminal-live/actions';
export type { TerminalOverlayContext, TerminalOverlayFactory } from '../../opscenter/cells/terminal-live/actions';
export type { ControllerLike } from '../../lib/terminal-search/search-host';

interface HostEvents {
  subscribe(handler: (frame: { type?: string }) => void): () => void;
}

export function onEventFrame<T extends { type?: string }>(type: string, handler: (frame: T) => void): () => void {
  const events = (globalThis as { AppEvents?: HostEvents }).AppEvents;
  if (!events || typeof events.subscribe !== 'function') return () => {};
  return events.subscribe((frame) => {
    if (frame && frame.type === type) handler(frame as T);
  });
}
