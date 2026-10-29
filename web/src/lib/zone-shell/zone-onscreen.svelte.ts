import { visibilityObserver } from '../visibility-observer';

let hidden = $state(typeof document !== 'undefined' && document.visibilityState === 'hidden');
let listening = false;

export function documentHidden(): boolean {
  if (!listening && typeof document !== 'undefined') {
    listening = true;
    document.addEventListener('visibilitychange', () => {
      hidden = document.visibilityState === 'hidden';
    });
  }
  return hidden;
}

type Report = (onScreen: boolean) => void;

let observer: IntersectionObserver | null = null;
const reports = new WeakMap<Element, Report>();

function shared(): IntersectionObserver | null {
  if (observer) return observer;
  const Observer = visibilityObserver();
  if (!Observer) return null;
  observer = new Observer((entries) => {
    for (const entry of entries) reports.get(entry.target)?.(entry.isIntersecting);
  });
  return observer;
}

export function observeOnScreen(el: Element, report: Report): () => void {
  const watcher = shared();
  if (!watcher) return () => {};
  reports.set(el, report);
  watcher.observe(el);
  return () => {
    watcher.unobserve(el);
    reports.delete(el);
  };
}
