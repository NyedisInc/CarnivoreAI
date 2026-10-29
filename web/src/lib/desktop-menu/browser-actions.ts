import { newSession, startNewProject, sessions } from '../../opscenter/api';
import { primarySessionId } from '../../opscenter/api/host';
import { rowFor } from '../../opscenter/cells/terminal-viewer/meta';
import { canOpenInTerminal, openInTerminal } from './open-in-terminal';
import { folderTargetId, revealInFinder, openInEditor } from './folder-actions';
import { hostDocument, hostWindow } from '../sessions/env';
import { terminalShown } from '../sessions-search/host';
import { wireMenuCommands, type MenuActions } from './menu-commands';

interface RowMenuGlobals {
  TerminalController?: { term?: unknown; _currentTmuxName?(): string | null };
  CloudeWeb?: { rowMenu?: { contextFromTrigger(el: Element | null): unknown } };
  SessionRowMenuActions?: { run(item: string, ctx: unknown): Promise<unknown> | void };
}

function sessionInViewContext(g: RowMenuGlobals): unknown {
  const ctl = g.TerminalController;
  if (!ctl || !ctl.term || typeof ctl._currentTmuxName !== 'function' || !terminalShown()) return null;
  const name = ctl._currentTmuxName();
  const doc = hostDocument();
  if (!name || !doc || typeof CSS === 'undefined') return null;
  const key = `[data-row-menu="${CSS.escape(name)}"]`;
  const trigger = doc.querySelector(`${key}[data-row-menu-surface="sidebar"]`) ?? doc.querySelector(key);
  return g.CloudeWeb?.rowMenu?.contextFromTrigger(trigger) ?? null;
}

export function browserMenuActions(): MenuActions {
  return {
    newSession: () => { newSession(null); },
    openProject: () => { startNewProject(); },
    sessionItem: (item) => {
      const g = (hostWindow() ?? {}) as RowMenuGlobals;
      const ctx = sessionInViewContext(g);
      if (ctx && g.SessionRowMenuActions) void g.SessionRowMenuActions.run(item, ctx);
    },
    openInTerminal: () => {
      const id = primarySessionId();
      const row = id ? rowFor(sessions.data, id) : null;
      if (id && canOpenInTerminal(id, row?.host_key, row?.tmux_session)) void openInTerminal(id);
    },
    reveal: (target) => {
      const id = folderTargetId(target, primarySessionId(), sessions.data);
      if (id) void revealInFinder(id);
    },
    openInEditor: (target) => {
      const id = folderTargetId(target, primarySessionId(), sessions.data);
      if (id) void openInEditor(id);
    },
  };
}

export function startMenuCommands(): void {
  wireMenuCommands(browserMenuActions());
}
