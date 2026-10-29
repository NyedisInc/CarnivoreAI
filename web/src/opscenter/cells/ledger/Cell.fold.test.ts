import { afterEach, describe, expect, it } from 'vitest';
import { LEDGER_WIDGET } from './Cell.svelte';

function installStore(folded: Set<string>): void {
  (globalThis as { SessionSidebarStore?: unknown }).SessionSidebarStore = {
    isCollapsed: (key: string) => folded.has(key),
    toggleCollapsed: (key: string) => (folded.delete(key) ? false : (folded.add(key), true)),
  };
}

describe('core.ledger declared fold', () => {
  afterEach(() => {
    delete (globalThis as { SessionSidebarStore?: unknown }).SessionSidebarStore;
  });

  it('is global, stateful and keeps its fold on the shared home', () => {
    expect(LEDGER_WIDGET.scope).toBe('global');
    const fold = LEDGER_WIDGET.state.fold;
    expect(fold.home).toBe('shared');
    expect(fold.default).toBe('compact');
  });

  it('reads and writes exactly the reserved ledger fold keys', () => {
    const folded = new Set<string>();
    installStore(folded);
    const { via, valid } = LEDGER_WIDGET.state.fold as unknown as { via: { read(): unknown; write(v: unknown): void }; valid(v: unknown): boolean };
    via.write('glance');
    expect([...folded]).toEqual(['ledger_glance']);
    expect(via.read()).toBe('glance');
    via.write('expanded');
    expect([...folded]).toEqual(['ledger_expanded']);
    via.write('nonsense');
    expect([...folded]).toEqual(['ledger_expanded']);
    expect(valid('hidden')).toBe(true);
    expect(valid('x')).toBe(false);
  });
});
