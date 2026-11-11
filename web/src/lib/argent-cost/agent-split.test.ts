import { describe, expect, it } from 'vitest';
import { agentSplitView, type ArgentCostSnapshot } from './cost-view';

const snap = (agents: unknown, over: Partial<ArgentCostSnapshot> = {}): ArgentCostSnapshot => ({
  enabled: true,
  state: 'ok',
  items: { wi_a: { name: 'story a' }, wi_b: { name: 'project b' } },
  sessions: { '7': { items: ['wi_a', 'wi_b'], agents: agents as never } },
  ...over,
});

describe('agentSplitView', () => {
  it('rolls the agents up per work item, root first, with the root unnamed', () => {
    const groups = agentSplitView(snap([
      { agent_id: '', name: null, item_id: 'wi_a', cost_micros: 900_000 },
      { agent_id: 'x1', name: 'write the poller', item_id: 'wi_a', cost_micros: 300_000 },
      { agent_id: 'y2', name: 'y2', item_id: 'wi_b', cost_micros: 34_500 },
    ]), 7);
    expect(groups?.map((g) => [g.itemName, g.totalText, g.agents.map((a) => a.name)])).toEqual([
      ['story a', '$1.20', [null, 'write the poller']],
      ['project b', '$0.0345', ['y2']],
    ]);
  });

  it('reads an unmeasured agent as - and never reads a partial sum as the whole', () => {
    const groups = agentSplitView(snap([
      { agent_id: '', item_id: 'wi_a', cost_micros: 900_000 },
      { agent_id: 'x1', item_id: 'wi_a', cost_micros: null },
    ]), 7);
    expect(groups?.[0]?.totalText).toBe('-');
    expect(groups?.[0]?.agents[1]?.costText).toBe('-');
  });

  it('draws nothing when off, not ok, no split, or another row (negative controls)', () => {
    const rows = [{ agent_id: '', item_id: 'wi_a', cost_micros: 1 }];
    expect(agentSplitView(snap(rows, { enabled: false }), 7)).toBeNull();
    expect(agentSplitView(snap(rows, { state: 'pending' }), 7)).toBeNull();
    expect(agentSplitView(snap(null), 7)).toBeNull();
    expect(agentSplitView(snap([]), 7)).toBeNull();
    expect(agentSplitView(snap(rows), 8)).toBeNull();
    expect(agentSplitView(snap(rows), 7)).not.toBeNull();
  });
});
