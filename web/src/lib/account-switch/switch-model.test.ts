import { describe, expect, test } from 'vitest';
import { activeAccountId, refusalCode, rowSwitchState, type AccountSwitchState } from './switch-model';
import { toastFor } from './switch-toast';

function state(claude: string | null, codex: string | null = null): AccountSwitchState {
  return {
    auto_switch: false,
    threshold_percent: 99,
    active: [
      { provider: 'claude', account_id: claude, source: claude ? 'pointer' : 'none', pointer: claude },
      { provider: 'codex', account_id: codex, source: codex ? 'pointer' : 'none', pointer: codex },
    ],
    last_switch: null,
    restarts_running_sessions: false,
  };
}

describe('rowSwitchState', () => {
  test('the active account is active and its siblings are switch targets', () => {
    const s = state('work');
    expect(rowSwitchState(s, { id: 'work', provider: 'claude' })).toBe('active');
    expect(rowSwitchState(s, { id: 'play', provider: 'claude' })).toBe('available');
  });

  test('a codex row is judged against the codex pointer, never the claude one', () => {
    const s = state('work', 'cx');
    expect(rowSwitchState(s, { id: 'work', provider: 'codex' })).toBe('available');
    expect(rowSwitchState(s, { id: 'cx', provider: 'codex' })).toBe('active');
  });

  test('an account signed in but not set up says so instead of offering a switch (issue #671)', () => {
    const s = state('work');
    expect(rowSwitchState(s, { id: 'play', provider: 'claude', setup_complete: false })).toBe('needs_setup');
    expect(rowSwitchState(s, { id: 'play', provider: 'claude', setup_complete: true })).toBe('available');
    expect(rowSwitchState(s, { id: 'play', provider: 'claude', setup_complete: null })).toBe('available');
    expect(rowSwitchState(s, { id: 'work', provider: 'claude', setup_complete: false })).toBe('active');
  });

  test('before the state is read nothing is claimed', () => {
    expect(rowSwitchState(null, { id: 'work', provider: 'claude' })).toBe('unknown');
  });

  test('a provider the switch does not cover draws no control', () => {
    expect(rowSwitchState(state('work'), { id: 'x', provider: 'hermes' })).toBe('unknown');
  });

  test('with nothing chosen every row is a target', () => {
    expect(rowSwitchState(state(null), { id: 'work', provider: 'claude' })).toBe('available');
    expect(activeAccountId(state(null), 'claude')).toBeNull();
  });
});

describe('refusalCode', () => {
  test('reads the code out of a FastAPI detail object', () => {
    expect(refusalCode({ detail: { code: 'profile_not_shared', detail: 'x' } })).toBe('profile_not_shared');
    expect(refusalCode({ detail: 'plain' })).toBeNull();
    expect(refusalCode(null)).toBeNull();
  });
});

describe('toastFor', () => {
  test('an automatic switch is a local card that belongs to no session', () => {
    const toast = toastFor({
      provider: 'claude', from_account_id: 'a', to_account_id: 'b', reason: 'auto',
      window_kind: 'five_hour', used_pct: 99, at: '2026-09-25T12:00:00Z',
    });
    expect(toast).not.toBeNull();
    expect(toast?.session_id).toBeNull();
    expect(toast?.local).toBe(true);
    expect(toast?.kind).toBe('AccountSwitched');
    expect(String(toast?.body)).toContain('99%');
  });

  test('the window is named by its length, so a codex "primary" 5h window says 5 hour', () => {
    const toast = toastFor({
      provider: 'codex', from_account_id: 'a', to_account_id: 'b', reason: 'auto',
      window_kind: 'primary', window_seconds: 18000, used_pct: 99,
    });
    expect(String(toast?.body)).toContain('5 hour');
    const week = toastFor({
      provider: 'claude', from_account_id: 'a', to_account_id: 'b', reason: 'auto',
      window_kind: 'seven_day', window_seconds: 604800, used_pct: 99,
    });
    expect(String(week?.body)).toContain('weekly');
  });

  test('an auto restart says a session was restarted, not that new sessions moved', () => {
    const toast = toastFor({ provider: 'claude', from_account_id: 'a', to_account_id: 'b', reason: 'auto_restart' });
    expect(String(toast?.title)).toContain('restarted');
    expect(String(toast?.body)).toContain('hit its limit');
  });

  test('a frame without a target raises nothing', () => {
    expect(toastFor({ provider: 'claude', reason: 'auto' })).toBeNull();
  });
});
