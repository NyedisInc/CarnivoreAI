import { describe, expect, it } from 'vitest';
import { META } from '../engine/meta';
import type { CellMeta } from '../engine/types';
import { registerPluginDeclaration } from './fit-declarations';
import { allManifests, manifestById, registerDraftManifest } from './core-manifests';
import { resolvePlacement } from './placement-resolve';
import { scopeForWidget, type SessionScope } from './session-scope';

const SCOPE: SessionScope = { sessionId: 'ses_1', rowId: 7, workingDir: '/tmp/x', projectId: null };

function registerSessionDraft(): string {
  registerPluginDeclaration({ id: 'pulse-board', instancing: 'singleton', fits: { sizes: ['medium'], anySize: false } });
  const meta = { ...META.notes, id: 'pulse-board' } as unknown as CellMeta;
  return registerDraftManifest('pulse-board', meta, { category: 'tools', type: 'list', capabilities: [], scope: 'session' }, ['home']).id;
}

describe('resolvePlacement', () => {
  it('resolves a registered draft in every host path and hands a session draft a scope', () => {
    const id = registerSessionDraft();
    expect(manifestById(id)).toBeDefined();
    expect(allManifests()[id]).toBeDefined();
    for (const ref of [{ widget: id }, { widget: id, view: null }, { widget: manifestById(id)! }]) {
      const resolved = resolvePlacement(ref);
      expect(resolved?.manifest.id).toBe(id);
      expect(resolved?.cell.id).toBe(id);
      expect(resolved?.slot).toBe('pulse-board');
      expect(scopeForWidget(resolved?.manifest, SCOPE)).toBe(SCOPE);
    }
  });

  it('answers null for a widget this build does not carry', () => {
    expect(resolvePlacement({ widget: 'core.nothing-here' })).toBeNull();
  });

  it('draws a view by its cell and marks the scope switch', () => {
    const all = resolvePlacement({ widget: 'core.tasks', view: 'all' });
    expect(all?.cell.id).toBe('core.tasks-all');
    expect(all?.iconWidget).toBe('core.tasks-all');
    expect(all?.scopeSwitch).toBe(true);
    const own = resolvePlacement({ widget: 'core.tasks', view: 'gone' });
    expect(own?.cell.id).toBe('core.tasks');
    expect(own?.view).toBe('session');
  });

  it('puts a family copy under <kind>:<target> and keeps the copy id', () => {
    const copy = resolvePlacement({ widget: 'core.analytics', target: 'abc', instance: 'two' });
    expect(copy?.slot).toBe('analytics:abc');
    expect(copy?.family).toBe(true);
    expect(copy?.instance).toBe('two');
    expect(resolvePlacement({ widget: 'core.notes' })?.family).toBe(false);
  });
});
