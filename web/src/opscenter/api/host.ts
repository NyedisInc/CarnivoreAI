
import { closeMenuPagesExcept } from '../../lib/menu-page/menu-page-shell.svelte';

interface WebNamespace {
  openCatalogScreen?: () => boolean;
  openThemesScreen?: () => boolean;
  openPluginsScreen?: () => boolean;
  openWidgetsScreen?: () => boolean;
  openWrappersScreen?: () => boolean;
  openHostsScreen?: () => boolean;
  openLedgerScreen?: (account?: string) => boolean;
  openBlueprintsScreen?: () => boolean;
  openSettingsScreen?: () => boolean;
  openSessionsScreen?: () => boolean;
  launchpad?: {
    openRunningSession?: (sessionId: string, tmuxName: string) => Promise<void>;
    selectProject?: (
      project: Record<string, unknown>,
      choice?: Record<string, unknown> | null,
    ) => Promise<void>;
    createNewSession?: () => Promise<void>;
    createConsoleSession?: (options?: { workingDir?: string | null } | null) => Promise<void>;
    openProjectFromFolder?: () => Promise<void>;
    startNewClaudeProject?: () => Promise<void>;
    startSessionInExistingProject?: () => Promise<void>;
    restartRecentSession?: (opts: Record<string, unknown>) => Promise<void>;
  };
}

interface AppGlobal {
  showLaunchpad?: () => void;
}

function web(): WebNamespace | null {
  return ((globalThis as { CloudeWeb?: unknown }).CloudeWeb as WebNamespace | undefined) ?? null;
}

function missing(member: string): false {
  console.error('CloudeOpscenter: ' + member + ' is not available, the action did nothing');
  return false;
}

function closeOtherMenuScreens(except: string): void {
  closeMenuPagesExcept(except);
}

export function openSession(
  sessionId: string | null | undefined,
  tmuxName: string | null | undefined,
): boolean {
  const id = (sessionId ?? '').trim();
  const name = (tmuxName ?? '').trim();
  if (!id && !name) {
    console.error(
      'CloudeOpscenter: the clicked row carried no session id and no tmux name, the action did nothing',
    );
    return false;
  }
  const open = web()?.launchpad?.openRunningSession;
  if (typeof open !== 'function') return missing('CloudeWeb.launchpad.openRunningSession');
  void open(id, name);
  return true;
}

/* the bottom bar */
export function primarySessionId(): string {
  const controller = (globalThis as { TerminalController?: unknown }).TerminalController as
    | { _sessionId?: () => string | null }
    | undefined;
  if (typeof controller?._sessionId !== 'function') return '';
  return (controller._sessionId() ?? '').trim();
}

export function primaryTmuxName(): string {
  const controller = (globalThis as { TerminalController?: unknown }).TerminalController as
    | { _currentTmuxName?: () => string | null }
    | undefined;
  if (typeof controller?._currentTmuxName !== 'function') return '';
  return (controller._currentTmuxName() ?? '').trim();
}

export function primaryTmuxEpoch(): number | null {
  const controller = (globalThis as { TerminalController?: unknown }).TerminalController as
    | { _unwrapSession?: (session: unknown) => { tmux_created_epoch?: unknown } | null; _currentSession?: unknown }
    | undefined;
  if (typeof controller?._unwrapSession !== 'function') return null;
  const raw = controller._unwrapSession(controller._currentSession)?.tmux_created_epoch;
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

/* nothing at all the project row */
export function newSession(project: Record<string, unknown> | null): boolean {
  const lp = web()?.launchpad;
  if (project) {
    if (typeof lp?.selectProject !== 'function') return missing('CloudeWeb.launchpad.selectProject');
    void lp.selectProject(project, null);
    return true;
  }
  return startNewSession('agent') !== null;
}

export function newTerminal(): boolean {
  return startNewSession('terminal') !== null;
}

/* navigation generation */
export function startNewSession(kind: 'agent' | 'terminal'): Promise<void> | null {
  const lp = web()?.launchpad;
  if (kind === 'agent') {
    if (typeof lp?.createNewSession !== 'function') return missing('CloudeWeb.launchpad.createNewSession') || null;
    return lp.createNewSession();
  }
  if (typeof lp?.createConsoleSession !== 'function') return missing('CloudeWeb.launchpad.createConsoleSession') || null;
  return lp.createConsoleSession({});
}

export function startNewSessionInProject(project: Record<string, unknown>): Promise<void> | null {
  const lp = web()?.launchpad;
  if (typeof lp?.selectProject !== 'function') return missing('CloudeWeb.launchpad.selectProject') || null;
  return lp.selectProject(project);
}

/* CANNOT DETERMINE running sessions */
export function startSessionInProject(): boolean {
  const start = web()?.launchpad?.startSessionInExistingProject;
  if (typeof start !== 'function') return missing('CloudeWeb.launchpad.startSessionInExistingProject');
  void start();
  return true;
}

/* running sessions */
export function startNewProject(): boolean {
  const start = web()?.launchpad?.startNewClaudeProject;
  if (typeof start !== 'function') return missing('CloudeWeb.launchpad.startNewClaudeProject');
  void start();
  return true;
}

/* conversation id */
export function resumeSession(record: {
  sessionUuid: string | null;
  title: string | null;
  workingDir: string | null;
  agentType: string | null;
}): boolean {
  const restart = web()?.launchpad?.restartRecentSession;
  if (typeof restart !== 'function') return missing('CloudeWeb.launchpad.restartRecentSession');
  void restart({
    sessionUuid: record.sessionUuid || null,
    title: (record.title ?? '').trim(),
    workingDir: record.workingDir ?? '',
    agentType: record.agentType ?? '',
  });
  return true;
}

export function openCatalog(): boolean {
  closeOtherMenuScreens('skills');
  const open = web()?.openCatalogScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openCatalogScreen');
  open();
  return true;
}

export function openBlueprints(): boolean {
  closeOtherMenuScreens('blueprints');
  const open = web()?.openBlueprintsScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openBlueprintsScreen');
  open();
  return true;
}

/* running sessions */
export function openSessions(): boolean {
  closeOtherMenuScreens('sessions');
  const open = web()?.openSessionsScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openSessionsScreen');
  open();
  return true;
}

export function openThemes(): boolean {
  closeOtherMenuScreens('themes');
  const open = web()?.openThemesScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openThemesScreen');
  open();
  return true;
}

/* the plugins page */
export function openPlugins(): boolean {
  closeOtherMenuScreens('plugins');
  const open = web()?.openPluginsScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openPluginsScreen');
  open();
  return true;
}

/* the widgets page */
export function openWidgets(): boolean {
  closeOtherMenuScreens('widgets');
  const open = web()?.openWidgetsScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openWidgetsScreen');
  open();
  return true;
}

export function openWrappers(): boolean {
  closeOtherMenuScreens('settings');
  const open = web()?.openWrappersScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openWrappersScreen');
  open();
  return true;
}

export function openHosts(): boolean {
  closeOtherMenuScreens('hosts');
  const open = web()?.openHostsScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openHostsScreen');
  open();
  return true;
}

export function openSettings(): boolean {
  closeOtherMenuScreens('settings');
  const open = web()?.openSettingsScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openSettingsScreen');
  open();
  return true;
}

export function importProject(): boolean {
  const open = web()?.launchpad?.openProjectFromFolder;
  if (typeof open !== 'function') return missing('CloudeWeb.launchpad.openProjectFromFolder');
  void open();
  return true;
}

export function newGroup(): boolean {
  const actions = (globalThis as { SessionSidebarGroupActions?: { createGroupThenAssign?: (name: null) => Promise<void> } })
    .SessionSidebarGroupActions;
  if (typeof actions?.createGroupThenAssign !== 'function') return missing('window.SessionSidebarGroupActions.createGroupThenAssign');
  void actions.createGroupThenAssign(null);
  return true;
}

export function openHome(): boolean {
  const app = (globalThis as { App?: unknown }).App as AppGlobal | undefined;
  if (typeof app?.showLaunchpad !== 'function') return missing('window.App.showLaunchpad');
  app.showLaunchpad();
  return true;
}

export function openLedger(): boolean {
  closeOtherMenuScreens('ledger');
  const open = web()?.openLedgerScreen;
  if (typeof open !== 'function') return missing('CloudeWeb.openLedgerScreen');
  open();
  return true;
}
