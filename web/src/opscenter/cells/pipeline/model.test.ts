import { describe, expect, test } from 'vitest';
import { areaOf, chartRows, sizeWords, OUTCOME_KEYS, PIPELINE_COLUMNS, pluginWords } from './model';
import { columnsFor } from '../../lib/run-chart';
import type { RecentRun } from '../../../lib/pipeline-status/api';
import { setLocale, t } from '../../../lib/i18n/index.svelte';

setLocale('en');

const NOW = 1_800_000_000;

function recent(over: Partial<RecentRun> = {}): RecentRun {
  return {
    plugin: 'stats', kind: 'delivery', scope: 'session', session_uuid: 'u1', session: 'fix login', project_id: 3,
    project: 'carnivore', conversation_id: 'c1', family: 'claude', trigger: 'live', finished_at: NOW - 42,
    duration_ms: 4.2, runs: 17, events: 3, outcome: 'ok', error: null, ...over,
  };
}

const nameOf = (plugin: string, rebuild: boolean) => pluginWords(t, plugin, rebuild);

describe('the friendly names', () => {
  test('a known plugin reads its catalog name, a rebuild says so, an unknown one renders its catalog key loudly', () => {
    expect(pluginWords(t, 'stats', false)).toBe('stats');
    expect(pluginWords(t, 'deepsearch', false)).toBe('deep search');
    expect(pluginWords(t, 'deepsearch', true)).toBe('deep search rebuild');
    expect(pluginWords(t, 'lineage', false)).toBe('pipeline.plugin_name.lineage');
    expect(pluginWords(t, 'caught_up', false)).toBe('pipeline.plugin_name.caught_up');
    expect(t(OUTCOME_KEYS.parked)).toBe('parked, retrying');
  });
});

describe('the area', () => {
  test('the session name, else the project, else the machine', () => {
    expect(areaOf(recent())).toBe('fix login');
    expect(areaOf(recent({ scope: 'project', session_uuid: null, session: null }))).toBe('carnivore');
    expect(areaOf(recent({ scope: 'session', session: null }))).toBe('carnivore');
    expect(areaOf(recent({ scope: 'machine', session: null, project: null }))).toBeNull();
  });
});

describe('chartRows', () => {
  test('one row per server row, in its order, with the name, area, run time, age and runs', () => {
    const rows = chartRows([recent(), recent({ plugin: 'deepsearch', kind: 'rebuild', scope: 'machine', session_uuid: null, session: null, project_id: null, project: null, finished_at: NOW - 600, duration_ms: 2500, runs: 1, outcome: 'failed', error: 'KeyError' })], NOW, nameOf);
    expect(rows.map((r) => [r.name, r.area, r.runMs, r.agoSeconds, r.runs, r.outcome])).toEqual([
      ['stats', 'fix login', 4.2, 42, 17, 'ok'],
      ['deep search rebuild', null, 2500, 600, 1, 'failed'],
    ]);
    expect(rows[0]!.id).toBe('session:u1:stats:delivery');
    expect(rows[1]!.id).toBe('machine::deepsearch:rebuild');
  });

  test('a plugin-contributed row names its area from the catalog, never a session or the machine', () => {
    const row = recent({ plugin: 'backups', scope: 'plugin', session_uuid: null, session: null, project_id: null, project: null });
    const [made] = chartRows([row], NOW, nameOf, (plugin) => t(`pipeline.plugin_area.${plugin}`));
    expect([made!.name, made!.area]).toEqual(['backups', 'conversations']);
    expect(chartRows([row], NOW, nameOf)[0]!.area).toBe('pipeline.plugin_area.backups');
  });

  test('an age in the future reads zero, never negative', () => {
    expect(chartRows([recent({ finished_at: NOW + 5 })], NOW, nameOf)[0]!.agoSeconds).toBe(0);
  });
});

describe('the columns', () => {
  test('narrow keeps name, area, run time and how long ago, tight drops the area; wide shows all five; the phone row is two lines', () => {
    expect(columnsFor(PIPELINE_COLUMNS, 300, false).map((c) => c.key)).toEqual(['name', 'area', 'runTime', 'ago']);
    expect(columnsFor(PIPELINE_COLUMNS, 220, false).map((c) => c.key)).toEqual(['name', 'runTime', 'ago']);
    expect(columnsFor(PIPELINE_COLUMNS, 500, false).map((c) => [c.key, c.minCh])).toEqual(
      [['name', undefined], ['area', undefined], ['runTime', 7], ['ago', 7], ['runs', 5]]);
    expect(columnsFor(PIPELINE_COLUMNS, 500, false).map((c) => c.key)).toEqual(['name', 'area', 'runTime', 'ago', 'runs']);
    expect(columnsFor(PIPELINE_COLUMNS, 500, true).map((c) => [c.key, c.line])).toEqual([['name', 1], ['ago', 1], ['area', 2], ['runTime', 2]]);
  });
});

describe('a seeded row', () => {
  test('null stays null, never zero, and the detail words come from the totals', () => {
    const row = recent({ plugin: 'backups', scope: 'plugin', duration_ms: null, runs: null, seeded: true, detail: { conversations: 2, size_bytes: 2048 } });
    const [made] = chartRows([row], NOW, nameOf, () => 'conversations', (d) => `${d.conversations}, ${sizeWords(d.size_bytes)}`);
    expect([made!.runMs, made!.runs, made!.detail]).toEqual([null, null, '2, 2.0 KB']);
    expect([sizeWords(0), sizeWords(1023), sizeWords(1536)]).toEqual(['0 B', '1023 B', '1.5 KB']);
  });
});
