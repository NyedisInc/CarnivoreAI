
export type TimerState = 'ok' | 'warning' | 'error' | 'disabled';

const KEYS: Readonly<Record<TimerState, string>> = {
  ok: 'automations.timer_state.ok',
  warning: 'automations.timer_state.warning',
  error: 'automations.timer_state.error',
  disabled: 'automations.timer_state.disabled',
};

export function timerStateOf(word: unknown): TimerState | null {
  return word === 'ok' || word === 'warning' || word === 'error' || word === 'disabled' ? word : null;
}

export function timerStateKey(state: TimerState): string {
  return KEYS[state];
}
