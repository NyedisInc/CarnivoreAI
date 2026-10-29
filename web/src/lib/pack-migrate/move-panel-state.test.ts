import { describe, expect, test } from 'vitest';
import { movePanelState, stepProgress } from './move-panel-state';

const base = { kind: 'project' as const, phase: 'pick' as const, machine: 'hosta', busy: false, error: null, canApply: null, opState: null };

describe('the move panel state', () => {
  test('walks loading, refused, ready, moving, done and failed from the store fields alone', () => {
    expect(movePanelState({ ...base, machine: null })).toBe('pick');
    expect(movePanelState({ ...base, busy: true })).toBe('checking');
    expect(movePanelState({ ...base, error: 'a different project here is already named x' })).toBe('refused');
    expect(movePanelState({ ...base, phase: 'plan', canApply: true })).toBe('ready');
    expect(movePanelState({ ...base, phase: 'plan', canApply: false })).toBe('refused');
    expect(movePanelState({ ...base, phase: 'running', opState: 'applying' })).toBe('moving');
    expect(movePanelState({ ...base, phase: 'running', opState: 'flipped' })).toBe('done');
    expect(movePanelState({ ...base, phase: 'running', opState: 'failed' })).toBe('failed');
    expect(movePanelState({ ...base, kind: 'back', machine: null, busy: true })).toBe('checking');
  });

  test('counts the op step as n of total, and nothing before the op reports one', () => {
    const steps = ['prepare', 'code', 'rows', 'transcripts', 'verify', 'flip'];
    expect(stepProgress('verify', steps)).toEqual({ n: 5, total: 6 });
    expect(stepProgress(null, steps)).toBeNull();
    expect(stepProgress('unknown', steps)).toBeNull();
  });
});
