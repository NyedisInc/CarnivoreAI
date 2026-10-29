import type { DeclaredAction } from '../../widgets/menu/declared-actions.svelte';
import { TOOLBAR_ITEMS } from './toolbar';
import { t } from '../../../lib/i18n/index.svelte';

export interface TerminalMenuInput {
  runItem: (id: string) => void;
  ready: (id: string) => boolean;
  zoom: { label: string; run: () => void } | null;
  sizeMaster: { on: boolean; run: () => void } | null;
  sleepLabel: string;
  notReady: string;
  applies?: (id: string) => boolean;
  popOut?: { label: string; run: () => void } | null;
}

const SHOWS = 'shows';
const DRAWERS = 'drawers';

function wordsOf(id: string): string {
  const key = TOOLBAR_ITEMS.find((item) => item.id === id)?.label;
  return key ? t(key) : id;
}

export function terminalMenuActions(input: TerminalMenuInput): DeclaredAction[] {
  const item = (id: string, group: string, label = wordsOf(id)): DeclaredAction => ({
    id,
    label,
    group,
    ...(input.ready(id) ? {} : { blocked: input.notReady }),
    run: () => input.runItem(id),
  });
  const applies = input.applies ?? (() => true);
  const drawers = ['skills', 'plugins', 'files', 'notes'].filter(applies).map((id) => item(id, DRAWERS));
  return [
    item('search', SHOWS),
    ...(input.zoom ? [{ id: 'zoom', label: input.zoom.label, group: SHOWS, run: input.zoom.run }] : []),
    item('theme', SHOWS),
    item('sleep', SHOWS, input.sleepLabel),
    ...(input.sizeMaster ? [{ id: 'size-master', label: wordsOf('size-master'), group: SHOWS, checked: input.sizeMaster.on, toggle: true, run: input.sizeMaster.run }] : []),
    ...drawers,
  ];
}

/* search terminal */
export function tabMenuActions(input: TerminalMenuInput): DeclaredAction[] {
  const search = terminalMenuActions(input).filter((action) => action.id === 'search');
  return input.popOut ? [...search, { id: 'pop-out', label: input.popOut.label, group: SHOWS, run: input.popOut.run }] : search;
}

export interface WidgetMenuInput extends TerminalMenuInput {
  menu: readonly string[];
  background: (() => void) | null;
  /* keep awake */
  keepAwake: { on: boolean; run: () => void } | null;
  bookmarks: (() => void) | null;
  rowActions: (() => void) | null;
  openInTerminal: (() => void) | null;
  words: { background: string; keepAwake: string; bookmarks: string; actions: string; openInTerminal: string };
}

const SESSION = 'session';

export function widgetMenuActions(input: WidgetMenuInput): DeclaredAction[] {
  const held = new Set(input.menu);
  const extra: DeclaredAction[] = [];
  if (held.has('background') && input.background) extra.push({ id: 'background', label: input.words.background, group: SHOWS, run: input.background });
  if (held.has('utilities') && input.bookmarks) extra.push({ id: 'bookmarks', label: input.words.bookmarks, group: SHOWS, run: input.bookmarks });
  if (held.has('utilities') && input.keepAwake) {
    extra.push({ id: 'keep-awake', label: input.words.keepAwake, group: SHOWS, checked: input.keepAwake.on, toggle: true, run: input.keepAwake.run });
  }
  if (input.popOut) extra.push({ id: 'pop-out', label: input.popOut.label, group: SHOWS, run: input.popOut.run });
  if (input.openInTerminal) extra.push({ id: 'open-in-terminal', label: input.words.openInTerminal, group: SHOWS, run: input.openInTerminal });
  const tools = terminalMenuActions(input).filter((action) => held.has(action.id));
  const shows = tools.filter((action) => action.group === SHOWS);
  const drawers = tools.filter((action) => action.group !== SHOWS);
  const session = input.rowActions ? [{ id: 'actions', label: input.words.actions, group: SESSION, run: input.rowActions }] : [];
  return [...shows, ...extra, ...drawers, ...session];
}
