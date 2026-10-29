import { describe, expect, test } from 'vitest';
import { describeDelta, formatDuration, formatMetric, formatSi } from './format';

describe('viz formatters', () => {
  test('SI, USD, duration and percent read from the catalog', () => {
    expect(formatSi(1234)).toBe('1.23k');
    expect(formatSi(5_000_000)).toBe('5M');
    expect(formatSi(5.88e9)).toBe('5.88B');
    expect(formatSi(2e12)).toBe('2T');
    expect(formatMetric(2_500_000_000, 'nano_usd')).toEqual({ text: '$2.50', unit: '' });
    expect(formatMetric(2_500_000_000, 'nano_usd/second').unit).toBe('/second');
    expect(formatDuration(3725)).toBe('1h 2m');
    expect(formatMetric(42.55, 'percent').text).toBe('42.6%');
    expect(formatMetric(null, 'tokens').text).toBe('no data');
  });

  test('delta says up or down in words with the percent, never arrows alone', () => {
    expect(describeDelta(120, 100)).toEqual({ direction: 'up', text: 'up 20%' });
    expect(describeDelta(75, 100)).toEqual({ direction: 'down', text: 'down 25%' });
    expect(describeDelta(100, 100).direction).toBe('flat');
    expect(describeDelta(5, 0).direction).toBe('none');
    expect(describeDelta(null, 5).direction).toBe('none');
  });
});
