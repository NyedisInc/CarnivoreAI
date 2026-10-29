/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { unavailableFindings } from './fit-probe';

function cell(plate: boolean): Element {
  const root = document.createElement('div');
  root.innerHTML = plate
    ? '<div class="oc-refusal" data-widget-unavailable data-widget-refusal="too-small"></div>'
    : '<div class="body">rows</div>';
  document.body.append(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('unavailableFindings', () => {
  test('goes red when the plate draws at a size the widget calls out, naming the reason', () => {
    const found = unavailableFindings(cell(true), true);
    expect(found).toHaveLength(1);
    expect(found[0]!.rule).toBe('unavailable');
    expect(found[0]!.detail).toContain('too-small');
  });

  test('stays quiet at a size the widget does not call out, and when the body is drawn', () => {
    expect(unavailableFindings(cell(true), false)).toEqual([]);
    expect(unavailableFindings(cell(false), true)).toEqual([]);
  });
});
