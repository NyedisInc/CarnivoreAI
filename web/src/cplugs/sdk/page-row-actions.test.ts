/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { PageRowActionConflict, pageRowActions, registerPageRowAction, resetPageRowActions, type PageRowAction } from './page-row-actions';

const action = (plugin: string, id: string, label = 'x'): PageRowAction => ({ plugin, id, label: () => label, enabled: () => true, targetOf: () => 't', run: () => {} });

afterEach(() => resetPageRowActions());

describe('page row actions', () => {
  it('lists enabled actions in registration order', () => {
    registerPageRowAction(action('a', 'one'));
    registerPageRowAction({ ...action('b', 'two'), enabled: () => false });
    registerPageRowAction(action('c', 'three'));
    expect(pageRowActions().map((x) => x.id)).toEqual(['one', 'three']);
  });

  it('lets a plugin register its own id again (a second start)', () => {
    registerPageRowAction(action('a', 'one', 'first'));
    registerPageRowAction(action('a', 'one', 'second'));
    expect(pageRowActions().map((x) => x.label())).toEqual(['second']);
  });

  it('refuses another plugin claiming the same id, and keeps the first', () => {
    registerPageRowAction(action('a', 'one', 'mine'));
    expect(() => registerPageRowAction(action('b', 'one', 'theirs'))).toThrow(PageRowActionConflict);
    expect(pageRowActions().map((x) => x.label())).toEqual(['mine']);
  });
});
