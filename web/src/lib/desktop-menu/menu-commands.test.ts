/** @vitest-environment jsdom */
import { createRequire } from 'node:module';
import path from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';

const apiCalls: string[] = [];
const opened: string[] = [];
const listing: { data: Array<{ session: { id: string }; tmux_session: string | null; host_key?: string }> } = { data: [] };
let inView = '';
vi.mock('../../opscenter/api/host', () => ({ primarySessionId: () => inView }));
vi.mock('./open-in-terminal', () => ({
  canOpenInTerminal: (_id: string, hostKey: string | undefined, tmux: string | null | undefined) => (!hostKey || hostKey === 'local') && !!tmux,
  openInTerminal: async (id: string) => { opened.push(id); },
}));
vi.mock('../../opscenter/api', () => ({
  sessions: { get data() { return listing.data; } },
  newSession: (project: unknown) => { apiCalls.push(`newSession:${String(project)}`); return true; },
  startNewProject: () => { apiCalls.push('startNewProject'); return true; },
}));

import { browserMenuActions } from './browser-actions';
import { KNOWN_VERBS, MENU_COMMAND_MESSAGE, handleMenuMessage, wireMenuCommands, type MenuActions } from './menu-commands';

function recorder(): { actions: MenuActions; log: string[] } {
  const log: string[] = [];
  return {
    log,
    actions: {
      newSession: () => log.push('newSession'),
      openProject: () => log.push('openProject'),
      sessionItem: (item) => log.push(`item:${item}`),
      openInTerminal: () => log.push('openInTerminal'),
      reveal: (target) => log.push(`reveal:${target}`),
      openInEditor: (target) => log.push(`editor:${target}`),
    },
  };
}
const msg = (verb: unknown) => ({ type: MENU_COMMAND_MESSAGE, verb });

describe('handleMenuMessage', () => {
  test('each known verb calls its entry point exactly once', () => {
    const expected: Record<string, string> = {
      'file.new_session': 'newSession', 'file.open_project': 'openProject', 'session.rename': 'item:rename',
      'session.restart': 'item:restart', 'session.stop': 'item:close', 'session.open_in': 'openInTerminal',
      'session.reveal': 'reveal:session', 'session.open_editor': 'editor:session',
      'file.reveal_project': 'reveal:project', 'file.open_project_editor': 'editor:project',
    };
    expect([...KNOWN_VERBS].sort()).toEqual(Object.keys(expected).sort());
    for (const [verb, call] of Object.entries(expected)) {
      const r = recorder();
      expect(handleMenuMessage(msg(verb), r.actions)).toBe(true);
      expect(r.log).toEqual([call]);
    }
  });
  test('an unknown verb, a wrong type and junk are ignored', () => {
    const r = recorder();
    for (const bad of [msg('rm.rf'), msg('constructor'), msg('__proto__'), msg(7), msg(undefined), { type: 'other', verb: 'file.new_session' }, null, 'x', 4]) {
      expect(handleMenuMessage(bad, r.actions)).toBe(false);
    }
    expect(r.log).toEqual([]);
  });
  test("the page's verbs are exactly main's fixed list (macOS/app-menu/commands.js)", () => {
    const require = createRequire(import.meta.url);
    const { MENU_VERBS } = require(path.resolve(__dirname, '../../../../macOS/app-menu/commands.js')) as { MENU_VERBS: string[] };
    expect([...MENU_VERBS].sort()).toEqual([...KNOWN_VERBS].sort());
  });
});

describe('wireMenuCommands', () => {
  test('accepts only a message the page posted to itself, from its own origin', () => {
    const r = recorder();
    const win = window;
    wireMenuCommands(r.actions, win);
    const send = (init: MessageEventInit) => win.dispatchEvent(new MessageEvent('message', { data: msg('file.new_session'), ...init }));
    send({ source: win, origin: win.location.origin });
    expect(r.log).toEqual(['newSession']);
    send({ source: win, origin: 'https://evil.example' });
    send({ source: null, origin: win.location.origin });
    send({ source: {} as MessageEventSource, origin: win.location.origin });
    expect(r.log).toEqual(['newSession']);
    wireMenuCommands(r.actions, win);
    send({ source: win, origin: win.location.origin });
    expect(r.log).toEqual(['newSession', 'newSession']);
  });
});

describe('browserMenuActions', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    apiCalls.length = 0;
    const w = window as unknown as Record<string, unknown>;
    delete w.TerminalController; delete w.CloudeWeb; delete w.SessionRowMenuActions;
  });

  function stage(name: string, viewName: string | null): string[] {
    const ran: string[] = [];
    const w = window as unknown as Record<string, unknown>;
    if (!(globalThis as { CSS?: unknown }).CSS) (globalThis as { CSS?: unknown }).CSS = { escape: (s: string) => s };
    document.body.innerHTML = `<button data-row-menu="${name}" data-row-menu-surface="sidebar"></button>`;
    w.TerminalController = { term: {}, _currentTmuxName: () => viewName };
    w.CloudeWeb = { rowMenu: { contextFromTrigger: (el: Element | null) => (el ? { name: el.getAttribute('data-row-menu') } : null) } };
    w.SessionRowMenuActions = { run: (item: string, ctx: { name: string }) => { ran.push(`${item}:${ctx.name}`); } };
    return ran;
  }

  test('new session and open project reach the drawer flows', () => {
    const a = browserMenuActions();
    a.newSession(); a.openProject();
    expect(apiCalls).toEqual(['newSession:null', 'startNewProject']);
  });
  test('a session item runs the row menu item on the session in view', () => {
    const ran = stage('carnivore_work', 'carnivore_work');
    const a = browserMenuActions();
    a.sessionItem('rename'); a.sessionItem('restart'); a.sessionItem('close');
    expect(ran).toEqual(['rename:carnivore_work', 'restart:carnivore_work', 'close:carnivore_work']);
  });
  test('open in terminal runs on the session in view when it is local and has a tmux name, else nothing', () => {
    const a = browserMenuActions();
    listing.data = [
      { session: { id: 'ses_1' }, tmux_session: 'carnivore_a', host_key: 'local' },
      { session: { id: 'ses_2' }, tmux_session: 'carnivore_b', host_key: 'peer-x' },
      { session: { id: 'ses_3' }, tmux_session: null },
    ];
    for (const id of ['ses_1', 'ses_2', 'ses_3', '']) { inView = id; a.openInTerminal(); }
    expect(opened).toEqual(['ses_1']);
  });
  test('no session in view, or no drawn row, does nothing', () => {
    let ran = stage('carnivore_work', null);
    browserMenuActions().sessionItem('close');
    expect(ran).toEqual([]);
    ran = stage('carnivore_work', 'carnivore_other');
    browserMenuActions().sessionItem('close');
    expect(ran).toEqual([]);
  });
});
