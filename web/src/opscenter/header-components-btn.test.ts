import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';

const css = readFileSync(new URL('../../../client/css/terminal-grid.css', import.meta.url), 'utf8');
const js = readFileSync(new URL('../../../client/js/header-menu.js', import.meta.url), 'utf8');

test('the grid-mounted rule shows the button and the click anchors on the button when it is drawn', () => {
  expect(css).toMatch(/body\.ps-grid-surface #headerComponentsBtn\s*\{\s*display:\s*flex;/);
  expect(js).toContain('openTerminalComponents(components.offsetParent !== null ? components : this.toggle)');
});
