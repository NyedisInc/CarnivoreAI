import { LIGHT_GROUND_MIN_L, srgbLightness, type Ground } from './characters/palette';

let flatten: CanvasRenderingContext2D | null = null;
let last: { css: string; ground: Ground } = { css: '', ground: 'dark' };

export const swarmGround = $state<{ ground: Ground }>({ ground: measureGround() });

export function measureGround(): Ground {
  if (typeof document === 'undefined' || typeof getComputedStyle === 'undefined') return 'dark';
  const css = getComputedStyle(document.documentElement).getPropertyValue('--oc-ground-panel').trim();
  if (!css) return 'dark';
  if (css === last.css) return last.ground;
  flatten ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  if (!flatten) return 'dark';
  flatten.clearRect(0, 0, 1, 1);
  flatten.fillStyle = '#000';
  flatten.fillStyle = css;
  flatten.fillRect(0, 0, 1, 1);
  const [r, g, b] = flatten.getImageData(0, 0, 1, 1).data;
  last = { css, ground: srgbLightness(r ?? 0, g ?? 0, b ?? 0) >= LIGHT_GROUND_MIN_L ? 'light' : 'dark' };
  return last.ground;
}

if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
  new MutationObserver(() => {
    const now = measureGround();
    if (now !== swarmGround.ground) swarmGround.ground = now;
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'style', 'class'] });
}
