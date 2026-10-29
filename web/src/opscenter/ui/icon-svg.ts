import { icons, type SizedIcon } from './icons';

export function iconSvgString(name: string, size = 20): string {
  const entry: string | SizedIcon | undefined = icons[name];
  if (!entry) return '';
  const path = typeof entry === 'string' ? entry : entry.path;
  const box = typeof entry === 'string' ? '0 0 24 24' : entry.viewBox;
  return `<svg width="${size}" height="${size}" viewBox="${box}" fill="none" stroke="currentColor" `
    + `stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" `
    + `focusable="false" data-icon="${name}">${path}</svg>`;
}
