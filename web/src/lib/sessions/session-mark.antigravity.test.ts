/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { beforeAll, expect, test } from 'vitest';
import { iconSvg } from '../../../../client/js/icons/icon-registry.js';
import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { faceFacts, providerMark, sessionMark } from './agent-marks';

beforeAll(() => {
  const REPO = path.resolve(__dirname, '../../../..');
  new Function(fs.readFileSync(path.join(REPO, 'client', 'js', 'agent-family-icon.js'), 'utf8'))();
  new Function(fs.readFileSync(path.join(REPO, 'client', 'js', 'wrapper-mark.js'), 'utf8'))();
  (globalThis as Record<string, unknown>).CloudeGlyphs = { glyphSvg, iconSvg };
});

test('a custom antigravity session wears the four-colour mark', () => {
  const svg = sessionMark('custom', 'logo-antigravity', 14).svg;
  for (const hue of ['#3186ff', '#00b95c', '#ffe432', '#fc413d']) expect(svg).toContain(hue);
  expect(svg).not.toContain('currentColor');
});

test('a custom agent with no picked icon keeps the family mark', () => {
  expect(sessionMark('custom', null, 14).svg).toContain('currentColor');
});

test('an asleep custom antigravity session preserves its wrapper icon in faceFacts', () => {
  const facts = faceFacts(
    { agent_family: 'custom', agent_wrapper_icon: 'logo-antigravity', unread: false },
    { lifecycle: 'asleep', transport: null },
  );
  expect(facts.family).toBe('custom');
  expect(facts.icon).toBe('logo-antigravity');
  expect(facts.status).toBe('asleep');
  const svg = sessionMark(facts.family, facts.icon, 14).svg;
  for (const hue of ['#3186ff', '#00b95c', '#ffe432', '#fc413d']) expect(svg).toContain(hue);
});

test('providerMark renders the four-colour antigravity vector mark for antigravity and agy (#3365)', () => {
  for (const name of ['antigravity', 'agy']) {
    const mark = providerMark(name, 14);
    expect(mark.key).toBe('antigravity');
    for (const hue of ['#3186ff', '#00b95c', '#ffe432', '#fc413d']) expect(mark.svg).toContain(hue);
    expect(mark.svg).not.toContain('currentColor');
  }
});
