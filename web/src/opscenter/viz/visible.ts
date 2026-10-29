import { visibilityObserver } from '../../lib/visibility-observer';

export function watchVisible(node: Element, set: (visible: boolean) => void): () => void {
  const Observer = visibilityObserver();
  if (!Observer) {
    set(true);
    return () => {};
  }
  const observer = new Observer((entries) => set(entries[0]?.isIntersecting ?? false));
  observer.observe(node);
  return () => observer.disconnect();
}
