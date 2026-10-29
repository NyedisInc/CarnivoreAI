import { mountFileDrawerHeader } from '../lib/file-drawer/file-drawer';
import { sessionList } from '../opscenter/widgets/fixtures/made-up';

export const NEEDS_BOUND_SESSION: ReadonlySet<string> = new Set([
  'core.notes', 'core.files', 'core.changes', 'core.task-manager', 'core.task-manager-mk2', 'core.timeline', 'core.session-contents',
  'core.tasks', 'core.bookmarks', 'core.automations', 'core.crosstalk', 'core.shell',
]);

interface ListedSession {
  session: { id: string; working_dir: string; pinned_theme: string | null };
  tmux_session: string;
}

export function bindSessionFor(widgetKey: string): void {
  if (!NEEDS_BOUND_SESSION.has(widgetKey)) return;
  const info = (sessionList() as ListedSession[])[0]!;
  const globals = globalThis as Record<string, unknown>;
  globals['TerminalController'] = {
    sessionActive: true,
    _currentSession: info,
    _sessionId: () => info.session.id,
    _currentTmuxName: () => info.tmux_session,
  };
  globals['CloudeWeb'] = { fileDrawer: { mountHeader: mountFileDrawerHeader, showCell: () => true } };
}
