import { readChoice, writeChoice } from './stored-choice';

export const VIEWS = ['list', 'pivot', 'timeline'] as const;
export type SessionsView = (typeof VIEWS)[number];

const KEY = 'carnivore.sessions-page.view';

export function readView(): SessionsView {
    return readChoice(KEY, VIEWS, 'list');
}

export function writeView(view: SessionsView): void {
    writeChoice(KEY, view);
}
