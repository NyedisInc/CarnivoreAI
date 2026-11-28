/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { rewriteRetiredWidgetUrl, widgetFromSearch } from './popout';

const CASES: Array<[string, string]> = [
  ['core.task-manager', 'core.task-manager-mk2'],
  ['core.task-list', 'core.task-manager-mk2'],
  ['core.task-manager-all', 'core.task-manager-mk2-all'],
];

afterEach(() => window.history.replaceState(null, '', '/'));

for (const [retired, successor] of CASES) {
  test(`?widget=${retired} reads as ${successor}`, () => {
    expect(widgetFromSearch(`?widget=${retired}`)).toBe(successor);
  });

  test(`a window restored at ?widget=${retired} rewrites its URL to ${successor}, keeping the placement`, () => {
    window.history.replaceState(null, '', `/static/popout.html?widget=${retired}&session=ses_1`);
    rewriteRetiredWidgetUrl(window);
    expect(new URLSearchParams(window.location.search).get('widget')).toBe(successor);
    expect(new URLSearchParams(window.location.search).get('session')).toBe('ses_1');
  });
}

test('a current widget id is left alone and its URL is not touched', () => {
  window.history.replaceState(null, '', '/static/popout.html?widget=core.notes');
  rewriteRetiredWidgetUrl(window);
  expect(window.location.search).toBe('?widget=core.notes');
  expect(widgetFromSearch('?widget=core.notes')).toBe('core.notes');
});
