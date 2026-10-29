/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { menuConformance } from './menu-conformance';

function drawCell(body: string): HTMLElement {
  const cell = document.createElement('div');
  cell.setAttribute('data-harness-cell', '');
  cell.innerHTML = `<header data-widget-head=""><span>files</span><button type="button" aria-haspopup="menu">menu</button></header>
    <div class="oc-frame-body">${body}</div>`;
  document.body.append(cell);
  return cell;
}

const ROWS = `<div role="tree"><div class="fx-row" role="treeitem" tabindex="0">src</div><div class="fx-row" role="treeitem" tabindex="-1">docs</div></div>`;

describe('the menu draw check', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('flags a menu button in the body (the files redesign draft)', () => {
    const cell = drawCell(`<div class="bar"><button type="button" class="fx-more" aria-haspopup="menu">more</button></div>${ROWS}`);
    const found = menuConformance(cell, 'core.files-redesign');
    expect(found.map((f) => f.rule)).toEqual(['menu-button-in-body']);
    expect(found[0]!.selector).toBe('button.fx-more');
  });

  it('passes a cell whose only menu button is the host\'s, and does not ask rows for a menu', () => {
    expect(menuConformance(drawCell(ROWS), 'core.files-redesign')).toEqual([]);
  });

  it('a waived widget is not flagged for what its ruling allows (the terminal kebab)', () => {
    const cell = drawCell('<button type="button" aria-haspopup="menu">kebab</button>');
    expect(menuConformance(cell, 'core.terminal')).toEqual([]);
    expect(menuConformance(cell, 'core.notes').map((f) => f.rule)).toEqual(['menu-button-in-body']);
  });
});
