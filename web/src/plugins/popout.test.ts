import { existsSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { CplugManifest } from './sdk';
import { buildPopoutList, POPOUT_CPLUGS } from './popout';

const part = (id: string) => ({ id, manifest: { id } as CplugManifest, tabs: [] });

describe('buildPopoutList', () => {
  it('orders by the hint, then by id, and keeps only pop-out parts', () => {
    const list = buildPopoutList({ './zed/popout.ts': { zedPopout: part('zed'), helper: () => 1 }, './reviewboard/popout.ts': { reviewboardPopout: part('reviewboard') }, './huddle/popout.ts': { taskManagerPopout: part('huddle') }, './abc/popout.ts': { abcPopout: part('abc') } });
    expect(list.map((p) => p.id)).toEqual(['huddle', 'reviewboard', 'abc', 'zed']);
  });

  it('lists nothing for no plugin and is the same with one plugin folder gone', () => {
    expect(buildPopoutList({})).toEqual([]);
    expect(buildPopoutList({ './flow/popout.ts': { flowPopout: part('flow') } }).map((p) => p.id)).toEqual(['flow']);
  });
});

describe('POPOUT_CPLUGS', () => {
  it('finds every shipped plugin that has a pop-out part, in the order it always had', () => {
    const expected = ['huddle', 'flow', 'reviewboard', 'devwidgetlab'].filter((id) => existsSync(new URL(`./${id}`, import.meta.url)));
    expect(POPOUT_CPLUGS.map((p) => p.id)).toEqual(expected);
  });
});
