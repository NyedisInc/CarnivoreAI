import { describe, expect, test } from 'vitest';
import { pressureLine } from './pressure-line';
import type { PressureBlock } from '../pack-machines/pack-machines-store.svelte';

const t = (key: string, params: Record<string, string | number> = {}): string =>
  `${key}${Object.keys(params).length ? `(${Object.entries(params).map(([k, v]) => `${k}=${v}`).join(',')})` : ''}`;

const block = (over: Partial<PressureBlock>): PressureBlock => ({
  pegged: true, since: 1700000000, busy_cores: null, line: null, cores: null, run_queue_per_core: null, mem: null, ...over,
});

describe('pressureLine', () => {
  test('every figure uses its own key', () => {
    const line = pressureLine(block({ busy_cores: 7, cores: 8, line: 6, run_queue_per_core: 2.1, mem: 'warn' }), t);
    expect(line).toMatch(/^roster\.can\.peg\.since\(time=\d\d:\d\d\): /);
    expect(line).toContain('roster.can.peg.cores_line(busy=7,cores=8,line=6)');
    expect(line).toContain('; roster.can.peg.queue(n=2.1); roster.can.peg.mem_warn');
  });
  test('busy cores at or under the line never claim to be over it', () => {
    const line = pressureLine(block({ busy_cores: 6.3, cores: 10, line: 9, run_queue_per_core: 2.1 }), t);
    expect(line).toContain('roster.can.peg.cores(busy=6.3,cores=10)');
    expect(line).not.toContain('cores_line');
  });
  test('no line figure uses the shorter key, critical memory its own key', () => {
    const line = pressureLine(block({ busy_cores: 7.25, cores: 8, mem: 'critical' }), t);
    expect(line).toContain('roster.can.peg.cores(busy=7.3,cores=8)');
    expect(line).toContain('roster.can.peg.mem_critical');
  });
  test('a block with why set and no figures prints no server text', () => {
    const line = pressureLine(block({ since: null, why: 'busy cores 7.0 over the reserve line 6.0' }), t);
    expect(line).toBe('roster.can.peg.now');
    expect(line).not.toContain('busy cores');
  });
  test('a calm computer says so, and a missing figure is not shown as zero', () => {
    expect(pressureLine(block({ pegged: false, why: 'x' }), t)).toBe('roster.can.calm');
    expect(pressureLine(block({ run_queue_per_core: null }), t)).not.toContain('queue');
  });
});
