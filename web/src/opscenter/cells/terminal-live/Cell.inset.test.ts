import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from 'vitest';

const HERE = path.resolve(__dirname);
const WEB = path.resolve(HERE, '..', '..', '..', '..');

const SCROLLBAR_RESERVE_PX = 16;

const cell = fs.readFileSync(path.join(HERE, 'Cell.svelte'), 'utf8');
const tokens = fs.readFileSync(path.join(WEB, 'src', 'opscenter', 'tokens.css'), 'utf8');

function paneRule(): string {
  const at = cell.indexOf(':global(.oc-tl-pane) {');
  expect(at, 'the .oc-tl-pane rule is gone or renamed').toBeGreaterThan(-1);
  return cell.slice(at, cell.indexOf('}', at));
}

test('the inset is declared as a token and the host rule reads that token', () => {
  expect(tokens).toMatch(/--oc-terminal-inset:\s*\d+px;/);
  expect(paneRule()).toContain('padding-left: var(--oc-terminal-inset)');
});

test('the inset is no wider than the scrollbar reserve it is spent out of', () => {
  const found = /--oc-terminal-inset:\s*(\d+)px;/.exec(tokens);
  expect(found, 'the inset token is gone').not.toBeNull();
  const inset = Number((found as RegExpExecArray)[1]);
  expect(inset).toBeGreaterThan(0);
  expect(inset).toBeLessThanOrEqual(SCROLLBAR_RESERVE_PX);
});

test('the host takes no padding on the axis that costs rows', () => {
  const rule = paneRule();
  for (const side of ['padding-top', 'padding-bottom', 'padding-right', 'padding:']) {
    expect(rule, `${side} on the host would move the grid the user is reading`)
      .not.toContain(side);
  }
});
