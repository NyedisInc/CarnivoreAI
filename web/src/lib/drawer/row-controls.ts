import { PIN_SVG, pinAttrs } from '../sidebar-shell/row-chips';

export function escAttr(value: unknown): string {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export function escHtml(value: unknown): string {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML.replace(/"/g, '&quot;');
}

export function pinLegendHtml(pinned: boolean): string {
  const attrs = { ...pinAttrs('example', pinned), disabled: '', 'aria-hidden': 'true' };
  const text = Object.entries(attrs)
    .map(([k, v]) => (v === '' ? k : `${k}="${escAttr(v)}"`))
    .join(' ');
  return `<button ${text}>${PIN_SVG}</button>`;
}
