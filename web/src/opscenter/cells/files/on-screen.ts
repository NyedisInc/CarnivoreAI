/*  hidden  */
import { watchVisible } from '../../viz/visible';

export function watchOnScreen(node: Element, set: (onScreen: boolean) => void): () => void {
  let intersecting = false;
  const page = (): boolean => typeof document === 'undefined' || document.visibilityState !== 'hidden';
  const report = (): void => set(intersecting && page());
  const stopVisible = watchVisible(node, (yes) => {
    intersecting = yes;
    report();
  });
  report();
  if (typeof document === 'undefined') return stopVisible;
  document.addEventListener('visibilitychange', report);
  return () => {
    stopVisible();
    document.removeEventListener('visibilitychange', report);
  };
}
