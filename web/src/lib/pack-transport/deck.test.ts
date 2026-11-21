import { describe, expect, test } from 'vitest';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';
import { chipRows, keyWords } from './abilities-words';
import { hintFor, isOld, isTicked, type HintFacts } from './delegate-rows';

const machine = (over: Partial<PackMachine>): PackMachine => ({
  install_id: 'iid', label: 'tower', is_self: false, is_master: false, paired: true, state: 'connected', capabilities: ['pack.jobs'], specs: null, snapshot: null, age_seconds: 1, ...over,
});
const catalog: Record<string, string> = {
  'pack.autodelegate.state.old': 'remote carnivore needs update', 'pack.autodelegate.state.offline': 'not connected', 'pack.autodelegate.state.with_no_work': '{state}, does not take work',
  'pack.autodelegate.state.no_work': 'does not take work', 'pack.autodelegate.state.never': 'never used for this project', 'pack.deck.cap.cores': '{n} cores',
  'pack.deck.cap.memory': '{n} gb memory', 'pack.deck.cap.gpu': 'gpu {model}{vram}', 'pack.deck.cap.xcode': 'xcode {v}', 'roster.can.ios_sim': 'ios simulator',
};
const t = (key: string, vars: Record<string, string> = {}): string => (catalog[key] ?? key).replace(/\{(\w+)\}/g, (_m, k: string) => vars[k] ?? '');
const facts = (over: Partial<HintFacts> = {}): HintFacts => ({ never: false, hasCopy: false, takesWork: true, refused: null, copying: false, ...over });

describe('the computers a project may use', () => {
  test('a connected computer without pack.jobs is old: unchecked by default, even when it is not on the never-use list', () => {
    const old = machine({ capabilities: [] });
    expect(isOld(old)).toBe(true);
    expect(isTicked(old, [])).toBe(false);
    expect(hintFor(old, facts(), t, () => '')).toBe('remote carnivore needs update');
    expect(isTicked(machine({}), [])).toBe(true);
    expect(isTicked(machine({}), ['iid'])).toBe(false);
  });

  test('an away computer is not old, and a plain state says nothing', () => {
    expect(isOld(machine({ state: 'disconnected', capabilities: [] }))).toBe(false);
    expect(hintFor(machine({ state: 'disconnected' }), facts(), t, () => '')).toBe('not connected');
    expect(hintFor(machine({}), facts({ hasCopy: true }), t, () => '')).toBe('');
    expect(hintFor(machine({}), facts(), t, () => '')).toBe('');
  });
});

describe('what computers have', () => {
  test('the chips put the interesting facts first and the basic tools in their own quieter row', () => {
    const rows = chipRows({ os: 'macos', os_version: '15.1', chip: 'm4 max', cores: 16, mem_gb: 64, xcode: '16.1', ios_sim: true, tools: { git: true, playwright: true, node: false } }, t);
    expect(rows.main).toEqual(['macos 15.1', 'm4 max', '16 cores', '64 gb memory', 'xcode 16.1', 'ios simulator', 'playwright']);
    expect(rows.basic).toEqual(['git']);
    expect(keyWords({ xcode: '16.1', tools: { playwright: true, git: true } })).toEqual(['xcode', 'playwright']);
  });
});
