/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ApprovalDiff from './ApprovalDiff.svelte';
import { diffRows, diffValue } from './approvals-model';

describe('approval diff', () => {
  it('reads only well-formed rows off the shown arguments', () => {
    const item = { id: 'a', args: { diff: [{ field: 'cron', before: '0 7 * * 1', after: '0 8 * * 1' }, { nope: 1 }, null] } };
    expect(diffRows(item)).toEqual([{ field: 'cron', before: '0 7 * * 1', after: '0 8 * * 1' }]);
    expect(diffRows({})).toEqual([]);
    expect(diffValue({ a: 1 })).toBe('{"a":1}');
  });

  it('draws one row per field with now and becomes', () => {
    const host = document.createElement('div');
    document.body.append(host);
    const rows = [{ field: 'cron', before: '0 7 * * 1', after: '0 8 * * 1' }, { field: 'description', before: null, after: 'weekly' }];
    const view = mount(ApprovalDiff, { target: host, props: { rows } });
    flushSync();
    const drawn = host.querySelectorAll('tbody tr');
    expect(drawn.length).toBe(2);
    expect(drawn[0]!.querySelector('.ap-diff__before')?.textContent).toBe('0 7 * * 1');
    expect(drawn[0]!.querySelector('.ap-diff__after')?.textContent).toBe('0 8 * * 1');
    expect(drawn[1]!.querySelector('.ap-diff__before')?.textContent).not.toBe('null');
    unmount(view);
    host.remove();
  });
});
