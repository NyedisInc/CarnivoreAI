/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import HistoryBar from './HistoryBar.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

describe('the u chip presence mark', () => {
  it('marks a present visitor\'s chip and only that one', async () => {
    app = mount(HistoryBar, { target: document.body, props: {
      items: [{ kind: 'revision', id: 'r1', milestone: null }], folded: null, current: 'r1', total: 1, onpick: () => undefined, onunfold: () => undefined,
      visitors: [{ label: 'u1', number: 1, revision: 'r1', updated_at: 5, present: true }, { label: 'u2', number: 2, revision: 'r1', updated_at: 6, present: false }],
    } });
    await tick(); flushSync();
    const chip = (label: string): HTMLElement => document.querySelector<HTMLElement>(`[data-visitor="${label}"]`)!;
    expect(chip('u1').hasAttribute('data-present')).toBe(true);
    expect(chip('u1').getAttribute('aria-label')).toContain('viewing now');
    expect(chip('u2').hasAttribute('data-present')).toBe(false);
    expect(chip('u2').getAttribute('aria-label')).not.toContain('viewing');
  });
});
