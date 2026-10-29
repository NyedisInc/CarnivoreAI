import { CHANGED_EVENT } from '../auto-sleep/auto-sleep-store.svelte';

export function watchKeepAwakeRepaint(repaint: () => void, target: EventTarget = window): () => void {
    const onChange = (): void => repaint();
    target.addEventListener(CHANGED_EVENT, onChange);
    return () => target.removeEventListener(CHANGED_EVENT, onChange);
}
