import { describe, expect, test } from 'vitest';
import { moveGroups } from './move-options';

const keys = (o: { key: string }[]) => o.map((x) => x.key);

describe('moveGroups', () => {
  const companies = [{ id: 1, name: 'nyedis' }, { id: 2, name: 'Hartley' }, { id: 3, name: 'Acme' }];
  const projects = [
    { id: 10, name: 'zeta', company_id: 1 },
    { id: 11, name: 'Alpha', company_id: 2 },
    { id: 12, name: 'beta', company_id: 3 },
    { id: 13, name: 'Arbor', company_id: 1 },
    { id: 14, name: 'fds', company_id: null },
  ];

  test('active group first, companies then projects, case-insensitive A to Z in each group', () => {
    const sessions = [
      { project_id: 10, activity_status: 'working' },
      { project_id: 11, activity_status: 'idle' },
      { project_id: 12, activity_status: 'dead' },
      { project_id: 13, asleep: true, activity_status: 'idle' },
    ];
    const g = moveGroups(companies, projects, sessions);
    expect(keys(g.active)).toEqual(['c:Hartley', 'c:nyedis', 'p:Alpha', 'p:zeta']);
    expect(keys(g.others)).toEqual(['c:Acme', 'p:Arbor', 'p:beta', 'p:fds']);
  });

  test('no live session leaves the active group empty', () => {
    const g = moveGroups(companies, projects, [{ project_id: 10, activity_status: 'stopped' }]);
    expect(g.active).toEqual([]);
    expect(keys(g.others)).toEqual(['c:Acme', 'c:Hartley', 'c:nyedis', 'p:Alpha', 'p:Arbor', 'p:beta', 'p:fds', 'p:zeta']);
  });
});
