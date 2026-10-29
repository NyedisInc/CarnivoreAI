import { mountPanel } from '../../lib/mount';
import LayoutEditorHost from './LayoutEditorHost.svelte';

export const LAYOUT_EDITOR_HOST_ID = 'layout-editor-host';

export function mountLayoutEditor(): boolean {
  if (typeof document === 'undefined' || typeof document.getElementById !== 'function') return false;
  if (typeof document.createElement !== 'function' || typeof document.body?.appendChild !== 'function') return false;
  if (!document.getElementById(LAYOUT_EDITOR_HOST_ID)) {
    const host = document.createElement('div');
    if (!host || !host.style) return false;
    host.id = LAYOUT_EDITOR_HOST_ID;
    host.style.display = 'contents';
    document.body.appendChild(host);
  }
  return mountPanel(LAYOUT_EDITOR_HOST_ID, LayoutEditorHost, {}) !== null;
}
