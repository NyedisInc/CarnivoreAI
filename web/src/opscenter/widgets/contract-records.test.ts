import { describe, expect, test } from 'vitest';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { CORE_MANIFESTS } from './core-manifests';
import { allRecords, generalizeRoute, readRoutesOf, recordOf } from './contract-records';

const file = fileURLToPath(new URL('../../../../src/data/widget-contracts.json', import.meta.url));

if (process.env.CARNIVORE_WRITE_CONTRACTS === '1') {
  fs.writeFileSync(file, JSON.stringify({ schema: 1, widgets: allRecords() }, null, 2) + '\n');
}

const committed = JSON.parse(fs.readFileSync(file, 'utf8')) as { schema: number; widgets: unknown[] };

describe('src/data/widget-contracts.json', () => {
  test('there are records to compare (the control for the loops below)', () => {
    expect(allRecords().length).toBe(Object.keys(CORE_MANIFESTS).length);
    expect(committed.widgets.length).toBeGreaterThan(14);
  });

  test('is exactly what the registry derives, in registry order', () => {
    expect(committed.widgets).toEqual(JSON.parse(JSON.stringify(allRecords())));
  });

  test('a drifted record is not equal (the comparison can go red)', () => {
    const first = recordOf(Object.values(CORE_MANIFESTS)[0]!);
    expect({ ...first, sizes: ['full'] }).not.toEqual(first);
  });

  test('routes are generalized: a made-up session or list id becomes {id}', () => {
    expect(readRoutesOf('core.notes')).toContain('GET /sessions/{id}/note');
    expect(readRoutesOf('core.stat-sessions')).toContain('GET /sessions/list');
    expect(readRoutesOf('core.task-manager')).toContain('GET /cplugs/huddle/lists/{id}');
  });

  test('a collection route keeps its word and a made-up session id still generalizes', () => {
    expect(generalizeRoute('GET /sessions/list')).toBe('GET /sessions/list');
    expect(generalizeRoute('GET /sessions/asleep')).toBe('GET /sessions/asleep');
    expect(generalizeRoute('GET /sessions/ses_billingapi/tasks')).toBe('GET /sessions/{id}/tasks');
    expect(generalizeRoute('GET /sessions/9001/bookmarks')).toBe('GET /sessions/{id}/bookmarks');
  });

  test('a route a widget answers is a read even when every page asks it (the stat tiles read the listing)', () => {
    for (const id of ['core.stat-sessions', 'core.stat-running', 'core.stat-projects', 'core.stat-alive']) {
      expect(readRoutesOf(id), id).toContain('GET /sessions/list');
    }
    expect(readRoutesOf('core.stat-projects')).toContain('GET /projects');
    expect(readRoutesOf('core.notes')).not.toContain('GET /preferences');
  });

  test('every widget that ships a fixture says what it reads (no empty reads beside a real fixture)', () => {
    const silent = allRecords().filter((record) => record.fixtures.length > 0 && record.reads.length === 0).map((record) => record.id);
    expect(silent).toEqual([]);
  });
});
