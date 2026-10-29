/* the page terminal */
import { openFromDrawer, type OpenResult } from '../../../lib/open-files/open-bridge';
import { sessionRefFor } from '../../../lib/open-files/session-ref';

export const TERMINAL_HOST_ID = 'terminal-container';

interface EditorModal {
  open(rootId: string, relPath: string, readOnly: boolean, projectPath: string | null, placement: Placement | null): unknown;
  openView(title: string, subtitle: string, mount: (body: HTMLElement) => () => void, placement: Placement | null): unknown;
}

export interface Placement {
  host: HTMLElement;
  onFiles: () => void;
  stillCurrent: () => boolean;
}

function editor(): EditorModal | null {
  const found = (globalThis as { ConfigEditorModal?: EditorModal }).ConfigEditorModal;
  return found && typeof found.openView === 'function' ? found : null;
}

/* the page terminal */
export function placementFor(shows: () => boolean, onBack: () => void, doc: Document | null = typeof document !== 'undefined' ? document : null): Placement | null {
  const host = doc?.getElementById(TERMINAL_HOST_ID) ?? null;
  if (!host || !shows()) return null;
  return { host, onFiles: onBack, stillCurrent: shows };
}

export function openDiff(path: string, subtitle: string, mount: (body: HTMLElement) => () => void, placement: Placement | null): boolean {
  const found = editor();
  if (!found) return false;
  void found.openView(path, subtitle, mount, placement);
  return true;
}

export function openFile(path: string, repoRoot: string, placement: Placement | null): boolean {
  const found = editor();
  if (!found) return false;
  void found.open('workdir', path, false, repoRoot, placement);
  return true;
}

export interface RowRequest {
  path: string;
  kind: 'file' | 'diff';
}

export async function openAsRow(sessionId: string, request: RowRequest): Promise<OpenResult> {
  let ref;
  try {
    ref = await sessionRefFor(sessionId);
  } catch (err) {
    console.warn('changes: the session listing could not be read', { sessionId, error: err });
    return 'unavailable';
  }
  return openFromDrawer({ ...ref, root: 'workdir', path: request.path, kind: request.kind });
}
