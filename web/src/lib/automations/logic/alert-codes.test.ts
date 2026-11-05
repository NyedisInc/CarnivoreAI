/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { codesProblem, codesText, MAX_ALERT_CODES, parseCodes } from './alert-codes';
import { RUN_MARKS, lightOf, runMarkName } from './marks';
import { settledStatus, statusWord } from './words';

test('typed text becomes a deduplicated list, unreadable tokens stay for the error', () => {
  expect(parseCodes('10, 11 10')).toEqual([10, 11]);
  expect(parseCodes('')).toEqual([]);
  expect(parseCodes('ten')).toEqual(['ten']);
  expect(codesText([10, 11])).toBe('10, 11');
  expect(codesText(undefined)).toBe('');
});

test('the problem check matches the server rules', () => {
  expect(codesProblem(undefined)).toBe('');
  expect(codesProblem([10, 255, 1])).toBe('');
  for (const bad of [[0], [256], ['ten'], [1.5], [-1]]) expect(codesProblem(bad)).toBe('range');
  expect(codesProblem(Array.from({ length: MAX_ALERT_CODES + 1 }, (_, i) => i + 1))).toBe('count');
});

test('the cap equals the server MAX_ALERT_EXIT_CODES', () => {
  const models = readFileSync(`${process.cwd()}/../src/core/automations/models.py`, 'utf8');
  expect(Number(/^MAX_ALERT_EXIT_CODES = (\d+)/m.exec(models)![1])).toBe(MAX_ALERT_CODES);
});

test('alerted has its own mark, word and settled status, and lights the row', () => {
  expect(runMarkName('alerted')).toBe('alerted');
  expect(RUN_MARKS.alerted.length).toBeGreaterThan(0);
  expect(statusWord('alerted')).toBe('alerted');
  expect(settledStatus('alerted')).toBe(true);
  expect(lightOf(true, false, 'alerted')).toEqual({ kind: 'run', status: 'alerted' });
});

test('the alerted mark is painted in the cyan notice token, not the failure coral', () => {
  const css = readFileSync(`${process.cwd()}/src/lib/automations/auto-list.css`, 'utf8');
  expect(/\[data-status='alerted'\]\s*\{\s*color: var\(--oc-cyan\);/.test(css)).toBe(true);
  expect(/\[data-status='failed'\]\s*\{\s*color: var\(--oc-coral\);/.test(css)).toBe(true);
});
