import { mountPanel } from '../../lib/mount';
import { homeLayout } from '../engine/layout.svelte';
import { viewport } from '../engine/viewport.svelte';
import { editorSeams } from './editor.svelte';
import PopoutEditorHost from './PopoutEditorHost.svelte';

export const POPOUT_EDITOR_HOST_ID = 'popout-editor-host';

export function usePopoutEditorSeams(): void {
  editorSeams.page = () => 'home';
  editorSeams.store = (page) => (page === 'home' ? homeLayout : null);
  editorSeams.wide = () => viewport.wide;
}

export function startPopoutEditor(doc: Document = document, editNow = false): boolean {
  usePopoutEditorSeams();
  if (!doc.getElementById(POPOUT_EDITOR_HOST_ID)) {
    const host = doc.createElement('div');
    host.id = POPOUT_EDITOR_HOST_ID;
    host.style.display = 'contents';
    doc.body.appendChild(host);
  }
  return mountPanel(POPOUT_EDITOR_HOST_ID, PopoutEditorHost, { editNow }) !== null;
}
