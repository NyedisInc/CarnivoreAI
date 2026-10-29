import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { headerSteps } from './task-manager-tree';

const read = (file: string): string => readFileSync(new URL(file, import.meta.url), 'utf8');
const css = read('./task-manager-tree.css');

function padding(file: string, selector: string): string {
  const src = read(file);
  const at = src.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule ${selector} in ${file}`);
  return /padding:\s*([^;]+);/.exec(src.slice(at, src.indexOf('}', at)))![1]!;
}

function leftPx(value: string, step: number): number {
  const left = value.match(/calc\([^)]*\)\)|\S+/g)![3]!;
  const calc = /^calc\((\d+)px \+ var\(--hd-step, 0px\)\)$/.exec(left);
  return calc ? Number(calc[1]) + step : Number.parseInt(left, 10);
}

const OLD_ROW_FILE = ['Huddle', 'Row.svelte'].join('');

const STEP = 12;

describe('rows stay where they were', () => {
  test('the row stripe edge is the commit before the tree work', () => {
    const before = execFileSync('git', ['show', `2198b6cd7^:web/src/cplugs/huddle/${OLD_ROW_FILE}`], { cwd: new URL('.', import.meta.url).pathname, encoding: 'utf8' });
    const was = /\.hdr \{[^}]*?padding:\s*([^;]+);/.exec(before)![1]!;
    expect(padding('./TaskManagerRow.svelte', '.hdr')).toBe(was);
    expect(padding('./TaskManagerRow.svelte', '.hdr')).not.toContain('--hd-');
  });
  test('the lists add no margin or padding of their own', () => {
    for (const [file, sel] of [['./TaskManagerSections.svelte', '.hd-list'], ['./TaskManagerStatusSections.svelte', '.hss-list']]) {
      expect(padding(file!, sel!)).toBe('0');
    }
  });
});

describe('headers indent', () => {
  test('the status chevron sits right of the project chevron, the sub-header right of the status', () => {
    const project = Number.parseInt(padding('./TaskManagerProjectHead.svelte', '.hd-pchev').split(/\s+/)[3]!, 10);
    const status = leftPx(padding('./TaskManagerStatusSections.svelte', '.hss-head'), STEP);
    const area = leftPx(padding('./TaskManagerSections.svelte', '.hds-head'), STEP);
    const sub = leftPx(padding('./TaskManagerSubHead.svelte', '.hds-sub'), STEP);
    expect(status).toBeGreaterThan(project);
    expect(area).toBe(status);
    expect(sub).toBeGreaterThan(status);
  });
  test('the step is one spacing token, smaller on the phone, with no guide line', () => {
    expect(css).toMatch(/\.hd-block \{\s*--hd-step: var\(--oc-space-3\)/);
    expect(css).toMatch(/max-width: 700px\)[\s\S]*--hd-step: var\(--oc-space-2\)/);
    expect(css).not.toMatch(/box-shadow|#[0-9a-f]{3,8}\b|rgb\(/i);
  });
  test('depths', () => {
    expect([headerSteps('project'), headerSteps('header'), headerSteps('sub'), headerSteps('row')]).toEqual([0, 1, 2, 0]);
  });
});
