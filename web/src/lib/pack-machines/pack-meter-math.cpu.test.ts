import { describe, expect, it } from 'vitest';
import { cpuFigure, cpuPercent } from './pack-meter-math';

describe('cpuPercent', () => {
  it('uses busy cores, not the load average', () => {
    expect(Math.round(cpuPercent({ busy_cores: 1.76, load_1: 13.11, cores: 8 }) ?? -1)).toBe(22);
    expect(cpuFigure({ busy_cores: 1.76, load_1: 13.11, cores: 8 })).toBe('1.8/8');
  });
  it('falls back to load math when busy_cores is null', () => {
    expect(cpuPercent({ busy_cores: null, load_1: 5, cores: 10 })).toBe(50);
    expect(cpuPercent({ load_1: 13.11, cores: 8 })).toBe(100);
    expect(cpuPercent({ busy_cores: null, load_1: null, cores: 8 })).toBeNull();
  });
});
