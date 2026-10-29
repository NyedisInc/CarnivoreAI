import { describe, expect, test } from 'vitest';
import { compact, costText, dayLabel, firstLine, latencyText, modelName, percent, tokensText } from './calls-logic';

describe('calls-logic', () => {
    test('a model id splits into short name and provider', () => {
        expect(modelName('~anthropic/claude-sonnet-4.5')).toEqual({ name: 'claude-sonnet-4.5', provider: 'anthropic' });
        expect(modelName('qwen3')).toEqual({ name: 'qwen3', provider: '' });
        expect(modelName(null)).toEqual({ name: '', provider: '' });
    });
    test('numbers read short and never null', () => {
        expect(tokensText(378, 1800, 'in', 'out')).toBe('378 in / 1.8k out');
        expect(tokensText(null, null, 'in', 'out')).toBe('-');
        expect(compact(12500)).toBe('12.5k');
        expect(costText(0.0012)).toBe('$0.0012');
        expect(costText(null)).toBe('-');
        expect(latencyText(1234)).toBe('1.2s');
        expect(percent(3, 40)).toBe('8%');
        expect(firstLine('\n  401 unauthorized\nmore')).toBe('401 unauthorized');
    });
    test('days read today, yesterday, then a date', () => {
        const now = new Date(2026, 9, 12, 15, 0, 0);
        const at = (d: number) => new Date(2026, 9, d, 9, 0, 0).getTime() / 1000;
        expect(dayLabel(at(12), 'today', 'yesterday', now)).toBe('today');
        expect(dayLabel(at(11), 'today', 'yesterday', now)).toBe('yesterday');
        expect(dayLabel(at(9), 'today', 'yesterday', now)).toMatch(/Oct/);
    });
});
