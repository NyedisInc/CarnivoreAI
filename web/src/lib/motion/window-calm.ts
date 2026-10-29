
const ATTR = 'data-calm';
const EVENT = 'carnivore:calm';

export function windowCalm(): boolean {
  return typeof document !== 'undefined' && document.documentElement?.getAttribute(ATTR) != null;
}

export function calmReasons(): string[] {
  if (typeof document === 'undefined') return [];
  return (document.documentElement?.getAttribute(ATTR) ?? '').split(/\s+/).filter(Boolean);
}

export function watchWindowCalm(onChange: (calm: boolean) => void): () => void {
  if (typeof document === 'undefined') return () => {};
  const fire = (): void => onChange(windowCalm());
  document.addEventListener(EVENT, fire);
  return () => document.removeEventListener(EVENT, fire);
}
