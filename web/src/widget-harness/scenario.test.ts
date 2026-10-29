import { describe, expect, it } from 'vitest';
import { MAX_SCENARIO_CHARS, overlayScenario, parseScenario, tableToJson, unusedScenarioReads } from './scenario';

describe('parseScenario', () => {
  it('accepts routes keyed like a fixture and answers the table and the count', () => {
    const result = parseScenario('{"GET /sessions/list": [], "PUT /sessions/x/note": {"ok": true}}');
    expect(result).toEqual({ ok: true, routes: 2, table: { 'GET /sessions/list': [], 'PUT /sessions/x/note': { ok: true } } });
  });

  it.each([
    ['', 'the box is empty'],
    ['   ', 'the box is empty'],
    ['{"GET /x": ', 'this is not valid json'],
    ['[]', 'one json object'],
    ['"text"', 'one json object'],
    ['null', 'one json object'],
    ['{}', 'no routes'],
    ['{"sessions/list": []}', 'is not a route'],
    ['{"FETCH /x": 1}', 'is not a route'],
    ['{"GET  /x": 1}', 'is not a route'],
    ['{"__proto__": {"GET /x": 1}}', 'is not a route'],
  ])('refuses %j in plain words', (text, words) => {
    const result = parseScenario(text);
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.error).toContain(words);
  });

  it('pins the cap at one million characters, room for a real list with its threads', () => {
    expect(MAX_SCENARIO_CHARS).toBe(1_000_000);
    expect(parseScenario(`{"GET /x": "${'a'.repeat(300_000)}"}`).ok).toBe(true);
  });

  it('refuses a text past the size limit', () => {
    const result = parseScenario(`{"GET /x": "${'a'.repeat(MAX_SCENARIO_CHARS)}"}`);
    expect(result.ok).toBe(false);
  });

  it('only parses: code-looking text stays text and nothing runs', () => {
    const marker = '__scenario_ran__';
    (globalThis as Record<string, unknown>)[marker] = false;
    const result = parseScenario(`{"GET /x": "globalThis.${marker} = true", "GET /y": {"fn": "() => 1"}}`);
    expect(result.ok).toBe(true);
    expect((globalThis as Record<string, unknown>)[marker]).toBe(false);
    expect(result.ok && typeof (result.table['GET /x'] as unknown)).toBe('string');
    expect(result.ok && typeof (result.table['GET /y'] as { fn: unknown }).fn).toBe('string');
  });

  it('never refuses a function-shaped answer into a real function: JSON cannot carry one', () => {
    const result = parseScenario('{"GET /x": {"a": 1}}');
    expect(result.ok && Object.values(result.table).some((answer) => typeof answer === 'function')).toBe(false);
  });
});

describe('overlayScenario', () => {
  it('lays the scenario over the fixture: its routes win, the rest stay', () => {
    const table = overlayScenario({ 'GET /a': 1, 'GET /b': 2 }, { 'GET /b': 3 });
    expect(table).toEqual({ 'GET /a': 1, 'GET /b': 3 });
  });
});

describe('tableToJson', () => {
  it('writes the plain-data routes and leaves function answers out', () => {
    const json = tableToJson({ 'GET /a': { n: 1 }, 'GET /b': () => 2 });
    expect(JSON.parse(json)).toEqual({ 'GET /a': { n: 1 } });
  });
});

describe('unusedScenarioReads', () => {
  it('names a read the widget never asked for, and not a write or a prefix route', () => {
    const scenario = { 'GET /sessions/x/nte': 1, 'GET /sessions/x/note': 2, 'PUT /sessions/x/note': 3, 'GET /stats*': 4 };
    expect(unusedScenarioReads(scenario, ['GET /sessions/x/note'])).toEqual(['GET /sessions/x/nte']);
  });
});
