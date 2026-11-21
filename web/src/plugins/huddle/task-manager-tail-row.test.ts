import { describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { PROJECT_HEAD_HEIGHT_PX, PROJECT_HEAD_HEIGHT_TWO_ROW_PX, TAIL_OWN_ROW_BELOW_PX, projectHeadHeight } from './task-manager-sticky';

const head = readFileSync(new URL('./TaskManagerProjectHead.svelte', import.meta.url), 'utf8');
const body = readFileSync(new URL('./HuddleBody.svelte', import.meta.url), 'utf8');
const tail = readFileSync(new URL('./task-manager-tail.css', import.meta.url), 'utf8');
const narrow = `@container hdb (max-width: ${TAIL_OWN_ROW_BELOW_PX - 1}px)`;

function rule(source: string, selector: string): string {
  const at = source.indexOf(selector);
  expect(at).toBeGreaterThan(-1);
  return source.slice(source.indexOf('{', at), source.indexOf('}', at));
}

describe('narrow list: the tail takes its own row', () => {
  test('the list is the hdb container and the bar queries it at the shared threshold', () => {
    expect(rule(body, '.hd-scroll {')).toContain('container: hdb / inline-size');
    expect(body).toContain(narrow);
    expect(head).toContain(narrow);
  });

  test('the narrow bar is a two-row grid with the tail in the second row, full width, cells from one left edge', () => {
    const queried = head.slice(head.indexOf(narrow));
    expect(rule(queried, '.hd-group')).toMatch(/display: grid/);
    expect(rule(queried, '.hd-group')).toMatch(/grid-template-rows: 26px 22px/);
    expect(rule(queried, '.hd-pfill {')).toMatch(/grid-row: 2/);
    expect(rule(queried, '.hd-pfill {')).toMatch(/grid-column: 1 \/ -1/);
    const tailRow = tail.slice(tail.indexOf(narrow));
    expect(rule(tailRow, ".hd-tail {")).toMatch(/justify-content: start/);
    expect(rule(tailRow, ".hd-tail {")).toMatch(/overflow: visible/);
  });

  test('a wide bar stays inline: the flex bar and the end-anchored tail carry no query', () => {
    const base = head.slice(0, head.indexOf(narrow));
    expect(rule(base, '.hd-group {')).toMatch(/display: flex/);
    expect(rule(base, '.hd-pfill {')).toMatch(/justify-content: flex-end/);
  });

  test('the bar height follows the width, so the sticky math sees the taller bar', () => {
    expect(rule(body, narrow)).toContain(`--hd-phead-h: ${PROJECT_HEAD_HEIGHT_TWO_ROW_PX}px`);
    expect(projectHeadHeight(308)).toBe(PROJECT_HEAD_HEIGHT_TWO_ROW_PX);
    expect(projectHeadHeight(TAIL_OWN_ROW_BELOW_PX)).toBe(PROJECT_HEAD_HEIGHT_PX);
    expect(projectHeadHeight(0)).toBe(PROJECT_HEAD_HEIGHT_PX);
  });

  test('no filled cell is clipped and the title keeps its ellipsis and min-width', () => {
    expect(rule(tail, '.hd-slot {')).not.toMatch(/overflow/);
    expect(rule(tail, '.hd-tail-n {')).not.toMatch(/overflow/);
    const name = head.slice(head.indexOf('.hd-pname {\n      min-width'));
    expect(name).toMatch(/^[^}]*min-width: 0[^}]*overflow: hidden[^}]*text-overflow: ellipsis/);
    expect(head).toMatch(/grid-template-columns: auto auto minmax\(0, 1fr\)/);
  });
});
