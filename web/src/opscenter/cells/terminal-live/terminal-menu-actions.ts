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

export function tabMenuActions(input: TerminalMenuInput): DeclaredAction[] {
  const search = terminalMenuActions(input).filter((action) => action.id === 'search');
  return input.popOut ? [...search, { id: 'pop-out', label: input.popOut.label, group: SHOWS, run: input.popOut.run }] : search;
}

export interface WidgetMenuInput extends TerminalMenuInput {
  openInTerminal: (() => void) | null;
  words: { openInTerminal: string };
}

export function widgetMenuActions(input: WidgetMenuInput): DeclaredAction[] {
  const open: DeclaredAction[] = input.openInTerminal
    ? [{ id: 'open-in-terminal', label: input.words.openInTerminal, group: SHOWS, run: input.openInTerminal }]
    : [];
  return [...tabMenuActions(input), ...open];
}
