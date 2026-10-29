
export const NEEDS_TERMINAL_CLIENT: ReadonlySet<string> = new Set(['core.terminal', 'core.shell']);

export const STAND_IN_TRANSCRIPT: readonly string[] = [
  '$ git status',
  'on branch main',
  'tree is clean',
  '$ npm test',
  '48 tests passed',
  '$ ',
];

const COLLABORATOR_GLOBALS: readonly string[] = ['TerminalScroll', 'TerminalLayout', 'TerminalInputBuffer', 'AltScreenScroll', 'TerminalStartupNotice'];

interface StandInClient {
  init(): Promise<void>;
  reconnectToExistingSession(session: unknown): Promise<void>;
  dispose(): void;
}

export function createStandInClient(container: HTMLElement | null): StandInClient {
  let pane: HTMLElement | null = null;
  return {
    async init(): Promise<void> {
    },
    async reconnectToExistingSession(): Promise<void> {
      if (!container) return;
      pane = document.createElement('div');
      pane.className = 'xterm-stand-in';
      pane.dataset['standIn'] = 'terminal';
      pane.style.cssText = 'font-family:var(--font-mono);font-size:var(--oc-fs-body);line-height:1.3;white-space:pre;overflow:hidden;color:var(--oc-text-primary);';
      pane.textContent = STAND_IN_TRANSCRIPT.join('\n');
      container.appendChild(pane);
    },
    dispose(): void {
      pane?.remove();
      pane = null;
    },
  };
}

export function installTerminalStandIn(widgetKey: string): void {
  if (!NEEDS_TERMINAL_CLIENT.has(widgetKey)) return;
  const globals = globalThis as Record<string, unknown>;
  if (globals['CloudeTerminal']) return;
  globals['CloudeTerminal'] = { createTerminalClient: (container: HTMLElement | null) => createStandInClient(container) };
  for (const name of COLLABORATOR_GLOBALS) if (!globals[name]) globals[name] = { create: () => ({}) };
}
