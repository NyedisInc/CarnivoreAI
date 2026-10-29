import { hostWindow } from '../sessions/env';

export const MENU_COMMAND_MESSAGE = 'carnivore.menu-command';

export interface MenuActions {
  newSession(): void;
  openProject(): void;
  sessionItem(item: 'rename' | 'restart' | 'close'): void;
  openInTerminal(): void;
  reveal(target: 'session' | 'project'): void;
  openInEditor(target: 'session' | 'project'): void;
}

const VERBS: Readonly<Record<string, (actions: MenuActions) => void>> = Object.freeze({
  'file.new_session': (a) => a.newSession(),
  'file.open_project': (a) => a.openProject(),
  'session.rename': (a) => a.sessionItem('rename'),
  'session.restart': (a) => a.sessionItem('restart'),
  'session.stop': (a) => a.sessionItem('close'),
  'session.open_in': (a) => a.openInTerminal(),
  'session.reveal': (a) => a.reveal('session'),
  'session.open_editor': (a) => a.openInEditor('session'),
  'file.reveal_project': (a) => a.reveal('project'),
  'file.open_project_editor': (a) => a.openInEditor('project'),
});

export const KNOWN_VERBS: readonly string[] = Object.freeze(Object.keys(VERBS));

export function handleMenuMessage(data: unknown, actions: MenuActions): boolean {
  const msg = data as { type?: unknown; verb?: unknown } | null;
  if (!msg || msg.type !== MENU_COMMAND_MESSAGE || typeof msg.verb !== 'string') return false;
  const run = Object.prototype.hasOwnProperty.call(VERBS, msg.verb) ? VERBS[msg.verb] : undefined;
  if (!run) return false;
  run(actions);
  return true;
}

export function wireMenuCommands(actions: MenuActions, win: Window | undefined = hostWindow()): void {
  if (!win || (win as { __menuCommandsWired?: boolean }).__menuCommandsWired) return;
  (win as { __menuCommandsWired?: boolean }).__menuCommandsWired = true;
  win.addEventListener('message', (event: MessageEvent) => {
    if (event.source === win && event.origin === win.location.origin) handleMenuMessage(event.data, actions);
  });
}
