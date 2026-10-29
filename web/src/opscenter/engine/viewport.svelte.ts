/* there is nothing */

import { animationTypeOff } from '../../lib/motion/animation-types';
import { motionReduced } from '../../lib/motion/motion';

const QUERY = '(min-width: 1024px)';

const NARROW_QUERY = '(max-width: 767px)';

export const viewport: { wide: boolean; phone: boolean; narrow: boolean } = $state({ wide: true, phone: false, narrow: false });

export function reducedMotion(): boolean {
  return motionReduced() || animationTypeOff('layout-moves');
}

export function watchViewport(): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {};
  const query = window.matchMedia(QUERY);
  viewport.wide = query.matches;
  viewport.phone = !query.matches;
  const onChange = (event: MediaQueryListEvent): void => {
    viewport.wide = event.matches;
    viewport.phone = !event.matches;
  };
  query.addEventListener('change', onChange);
  const narrow = window.matchMedia(NARROW_QUERY);
  viewport.narrow = narrow.matches;
  const onNarrow = (event: MediaQueryListEvent): void => {
    viewport.narrow = event.matches;
  };
  narrow.addEventListener('change', onNarrow);
  return () => {
    query.removeEventListener('change', onChange);
    narrow.removeEventListener('change', onNarrow);
  };
}

export function pinGridViewport(): void {
  viewport.wide = true;
  viewport.phone = false;
  viewport.narrow = false;
}

if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  viewport.wide = window.matchMedia(QUERY).matches;
  viewport.phone = !viewport.wide;
  viewport.narrow = window.matchMedia(NARROW_QUERY).matches;
}

const STILL_ATTR = 'data-oc-still';

function watched(): boolean {
  if (typeof document === 'undefined') return true;
  if (document.visibilityState === 'hidden') return false;
  return typeof document.hasFocus === 'function' ? document.hasFocus() : true;
}

export function watchStillness(): () => void {
  if (typeof document === 'undefined' || typeof window === 'undefined') return () => {};
  const root = document.documentElement;
  const apply = (): void => {
    if (watched()) root.removeAttribute(STILL_ATTR);
    else root.setAttribute(STILL_ATTR, '');
  };
  apply();
  document.addEventListener('visibilitychange', apply);
  window.addEventListener('focus', apply);
  window.addEventListener('blur', apply);
  window.addEventListener('pageshow', apply);
  return () => {
    document.removeEventListener('visibilitychange', apply);
    window.removeEventListener('focus', apply);
    window.removeEventListener('blur', apply);
    window.removeEventListener('pageshow', apply);
    root.removeAttribute(STILL_ATTR);
  };
}
