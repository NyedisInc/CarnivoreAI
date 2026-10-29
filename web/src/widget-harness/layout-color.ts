/**
 * Color arithmetic for the layout-defect detector's contrast rule.
 *
 * Description: runs in the real browser. A computed color can come back in any
 *   syntax the engine likes (`rgb()`, `color(srgb ...)`, `oklab()` out of a
 *   `color-mix()`), so nothing here parses css text: the browser paints the
 *   color into a one-pixel canvas and the pixel is read back, which is the one
 *   parser that agrees with what is drawn. The effective background of a text
 *   run is found by walking its ancestors and compositing each translucent
 *   background over the next one down (source-over), WCAG 2.x relative
 *   luminance and contrast ratio on the result. `layout-defects.ts` is the
 *   only caller; `docs/widget-spec.md`, "The layout-defect check".
 */

export interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

/* could not */
export interface Backdrop {
  color: Rgba;
  certain: boolean;
}

const CANVAS_WHITE: Rgba = Object.freeze({ r: 255, g: 255, b: 255, a: 1 });

const cache = new Map<string, Rgba>();

let pixel: CanvasRenderingContext2D | null = null;

export function parseColor(css: string): Rgba {
  const hit = cache.get(css);
  if (hit) return hit;
  if (!pixel) {
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    pixel = canvas.getContext('2d', { willReadFrequently: true });
  }
  let out: Rgba = { r: 0, g: 0, b: 0, a: 0 };
  if (pixel) {
    pixel.clearRect(0, 0, 1, 1);
    pixel.fillStyle = '#000';
    pixel.fillStyle = css;
    pixel.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = pixel.getImageData(0, 0, 1, 1).data;
    out = { r: r ?? 0, g: g ?? 0, b: b ?? 0, a: (a ?? 0) / 255 };
  }
  cache.set(css, out);
  return out;
}

export function over(top: Rgba, under: Rgba): Rgba {
  const a = top.a + under.a * (1 - top.a);
  if (a <= 0) return { r: 0, g: 0, b: 0, a: 0 };
  const mix = (t: number, u: number): number => (t * top.a + u * under.a * (1 - top.a)) / a;
  return { r: mix(top.r, under.r), g: mix(top.g, under.g), b: mix(top.b, under.b), a };
}

function linear(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(color: Rgba): number {
  return 0.2126 * linear(color.r) + 0.7152 * linear(color.g) + 0.0722 * linear(color.b);
}

export function contrastRatio(a: Rgba, b: Rgba): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

export function effectiveBackground(el: Element): Backdrop {
  const layers: Rgba[] = [];
  let certain = true;
  for (let at: Element | null = el; at; at = at.parentElement) {
    const style = getComputedStyle(at);
    if (style.backgroundImage && style.backgroundImage !== 'none') certain = false;
    const color = parseColor(style.backgroundColor);
    if (color.a > 0) layers.push(color);
    if (color.a >= 1) break;
  }
  let ground = CANVAS_WHITE;
  for (let index = layers.length - 1; index >= 0; index -= 1) ground = over(layers[index]!, ground);
  return { color: ground, certain };
}

export function inheritedOpacity(el: Element): number {
  let product = 1;
  for (let at: Element | null = el; at; at = at.parentElement) product *= parseFloat(getComputedStyle(at).opacity) || 0;
  return product;
}
