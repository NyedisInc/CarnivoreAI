/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import TerminalActions from './TerminalActions.svelte';
import { planFolds } from './toolbar';

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
  sessions: { data: [{ session: { id: 'one' }, tmux_session: 'cloude_one', agent_type: 'claude' }], refresh: vi.fn() },
  asleep: { refresh: vi.fn() },
  sleepSession: vi.fn(),
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => '' }));

const RESTORED = ['skills', 'plugins', 'files', 'notes', 'theme', 'background'];
const KEPT = ['search', 'utilities', 'sleep', 'size-master'];
const UTILITIES = createRawSnippet(() => ({ render: () => '<span class="stub-utility"></span>' }));

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
});

function draw(width: number): { strip: string[]; kebab: string[] } {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalActions, { target, props: { slot: 'terminal:@primary', sessionId: 'one', width, utilities: UTILITIES, sessionName: 'cloude_one' } }));
  flushSync();
  const ids = (selector: string): string[] => [...target.querySelectorAll(`${selector} [data-tool]`)]
    .map((el) => el.getAttribute('data-tool') ?? '')
    .filter((id) => id !== 'overflow' && id !== 'actions');
  return { strip: ids('.cell-tools'), kebab: ids('.cell-options') };
}

test('a wide strip draws the kept icons, and the kebab holds every restored control', () => {
  const { strip, kebab } = draw(1000);
  expect(strip).toEqual(KEPT);
  expect(kebab).toEqual(RESTORED);
});

test('at every narrower width each icon is on the strip or in the kebab, exactly once', () => {
  for (const width of [636, 520, 400, 300, 200, 0]) {
    const { strip, kebab } = draw(width);
    for (const id of [...RESTORED, ...KEPT]) {
      expect(strip.includes(id) !== kebab.includes(id), `${id} at ${width}px`).toBe(true);
    }
  }
});

test('the least used strip icons fold first and search stays longest', () => {
  const folded = planFolds(0, 28, KEPT.map((id) => ({ id, width: 28, active: false })));
  expect(folded).toEqual(['utilities', 'size-master', 'sleep', 'search']);
});
