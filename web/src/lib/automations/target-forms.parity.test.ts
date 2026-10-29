import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { SEQUENCE_MAX_STEPS, SEQUENCE_MIN_STEPS, SEQUENCE_STEP_KINDS, SEQUENCE_LAST_KINDS, SEQUENCE_OMITTED_BY_DESIGN } from './target-forms';

const models = readFileSync(`${process.cwd()}/../src/core/automations/models.py`, 'utf8');
const tuple = (name: string): string[] => [...(models.match(new RegExp(`^${name} = \\(([^)]*)\\)`, 'm'))?.[1] ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1]!);

test('the step kinds equal the server tuple', () => {
  expect([...SEQUENCE_STEP_KINDS].sort()).toEqual(tuple('SEQUENCE_STEP_KINDS').sort());
});
test('the last-step kinds are the server tuple minus the ones left out on purpose', () => {
  const server = tuple('SEQUENCE_LAST_KINDS');
  expect(server.length).toBeGreaterThan(0);
  expect([...SEQUENCE_LAST_KINDS, ...SEQUENCE_OMITTED_BY_DESIGN].sort()).toEqual([...server].sort());
});
test('the step counts equal the server limits', () => {
  expect(models).toMatch(new RegExp(`^SEQUENCE_MAX_STEPS = ${SEQUENCE_MAX_STEPS}$`, 'm'));
  expect(models).toMatch(new RegExp(`steps: List\\[Dict\\[str, Any\\]\\] = Field\\(min_length=${SEQUENCE_MIN_STEPS}, `));
});
