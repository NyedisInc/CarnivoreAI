import { expect, test } from 'vitest';
import { fleetModel } from './fleet';
import { contextPlan } from '../../lib/sidebar-shell/row-context';

const row = (pct: unknown) => ({
  activity_status: 'working', session: { id: 'ses_a' }, tmux_session: 'a', label: 'a',
  running_model: 'claude-opus-5-5', running_context_used_pct: pct,
}) as never;

test('a fleet row and the sidebar row say the same percent and color step', () => {
  for (const pct of [3.2, 41.46, 41.5, 79.9, 94.5, 140]) {
    const fleet = fleetModel([row(pct)]).rows[0];
    const side = contextPlan({ name: 'a', running_context_used_pct: pct } as never);
    expect(fleet.context).toEqual(side && { pct: side.pct, scale: side.scale });
    expect(side?.label).toContain(String(fleet.contextSpoken));
  }
});

test('an unmeasured percent draws nothing and the model loses its vendor prefix', () => {
  const fleet = fleetModel([row(null)]).rows[0];
  expect(fleet.context).toBeNull();
  expect(fleet.contextSpoken).toBeNull();
  expect(fleet.model).toBe('opus-5-5');
});
