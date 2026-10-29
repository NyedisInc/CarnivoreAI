import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { GALLERY_CATEGORIES, PRESETS, presetConfig, presetNoteKey, presetTitleKey, type Preset } from './presets';
import { VIZ_KINDS, VIZ_SPECS } from './specs';

const repoRoot = path.resolve(__dirname, '../../../..');
const models = fs.readFileSync(path.join(repoRoot, 'src/models/stats.py'), 'utf8');
const catalog = fs.readFileSync(path.join(repoRoot, 'client/js/i18n/catalog.en.js'), 'utf8');

function literal(name: string): string[] {
  const body = new RegExp(`^${name} = Literal\\[([^\\]]*)\\]`, 'm').exec(models)?.[1] ?? '';
  return [...body.matchAll(/"([^"]+)"/g)].map((word) => word[1]!);
}
const METRICS = literal('Metric');
const DIMENSIONS = literal('Dimension');

function problems(preset: Preset): string[] {
  const out: string[] = [];
  if (!VIZ_KINDS.includes(preset.viz)) out.push('unknown viz');
  const allowed = VIZ_SPECS[preset.viz].options;
  for (const [key, value] of Object.entries(preset.options)) {
    if (!(key in allowed)) out.push(`option ${key} not accepted by ${preset.viz}`);
    else if (typeof value !== typeof allowed[key]) out.push(`option ${key} has the wrong type`);
  }
  if (preset.viz === 'leaderboard') { const n = preset.options['top_n']; if (typeof n !== 'number' || n < 1 || n > 10) out.push('top_n out of 1..10'); }
  if (preset.viz === 'treemap' && !['tokens', 'cost'].includes(String(preset.options['measure']))) out.push('measure must be tokens or cost');
  if (preset.series.length < 1 || preset.series.length > 12) out.push('series count');
  for (const series of preset.series) {
    if (!METRICS.includes(series.metric)) out.push(`unknown metric ${series.metric}`);
    if (series.group_by && !DIMENSIONS.includes(series.group_by)) out.push(`unknown dimension ${series.group_by}`);
    if (series.operation === 'ranking' && !series.group_by) out.push('ranking needs group_by');
    if (series.metric === 'quota_utilization' && series.group_by && !['account_id', 'window', 'provider'].includes(series.group_by)) out.push('quota grouping');
    if (series.group_by === 'window' && series.metric !== 'quota_utilization') out.push('window needs quota');
    if ((series.metric === 'quota_utilization' || series.metric.startsWith('average_')) && series.transform && series.transform !== 'total') out.push('transform');
  }
  if (preset.viz === 'leaderboard' && !preset.series[0]?.group_by) out.push('a leaderboard groups');
  if (preset.series.filter((series) => series.operation === 'comparison').length * 2 + preset.series.length > 12) out.push('expanded series');
  return out;
}

describe('the gallery presets', () => {
  test('the server vocabulary was actually read (a check that looked at nothing would pass)', () => {
    expect(METRICS.length).toBeGreaterThan(20);
    expect(DIMENSIONS).toContain('account_id');
  });

  test.each(PRESETS.map((preset) => [preset.id, preset] as const))('%s is a chart the server accepts', (_id, preset) => {
    expect(problems(preset)).toEqual([]);
  });

  test('the checker can go red', () => {
    const bad: Preset = { ...PRESETS[0]!, viz: 'leaderboard', options: { top_n: 99, nope: 1 }, series: [{ metric: 'not_a_metric', operation: 'ranking' }] };
    expect(problems(bad).length).toBeGreaterThanOrEqual(4);
  });

  test('ids are unique, every category holds a card, and every card has its two catalog strings', () => {
    expect(new Set(PRESETS.map((preset) => preset.id)).size).toBe(PRESETS.length);
    for (const category of GALLERY_CATEGORIES) expect(PRESETS.some((preset) => preset.category === category)).toBe(true);
    for (const preset of PRESETS) {
      expect(catalog).toContain(`'${presetTitleKey(preset)}':`);
      expect(catalog).toContain(`'${presetNoteKey(preset)}':`);
    }
  });

  test('every new renderer has a card and presetConfig gives a fresh, complete definition', () => {
    for (const viz of ['leaderboard', 'treemap', 'heat', 'vitals', 'hot', 'events', 'fleet', 'runway', 'swimlanes', 'flow', 'scatter', 'impact', 'health'] as const) expect(PRESETS.some((preset) => preset.viz === viz)).toBe(true);
    const made = presetConfig(PRESETS.find((preset) => preset.id === 'cost_by_model')!);
    expect(made).toMatchObject({ id: '', enabled: true, viz: 'timeline', display: { type: 'bar', stacked: true } });
    made.series[0]!.metric = 'x';
    expect(PRESETS.find((preset) => preset.id === 'cost_by_model')!.series[0]!.metric).toBe('estimated_cost_nano_usd');
  });
});
