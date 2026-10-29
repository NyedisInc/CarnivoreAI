import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

function read(rel: string): string {
  return fs.readFileSync(path.join(repoRoot, rel), 'utf8');
}

describe('the docked drawer leaves no seam before the home header', () => {
  test('the home screen pays the dock offset alone, inside its own unlayered padding', () => {
    const match = read('client/css/home-bar.css').match(/#launchpad-screen \{([^}]*)\}/);
    expect(match).not.toBeNull();
    expect(match![1]).toMatch(/padding:\s*0 0 0 var\(--dock-offset, 0\);/);
    expect(match![1]).not.toMatch(/--screen-pad-x/);
  });

  test('no negative-margin pull-back on the top bar, which .oc-app would clip', () => {
    const sidebar = read('client/css/session-sidebar.css');
    expect(sidebar).not.toMatch(/#launchpad-screen \.oc-topbar\s*\{/);
    expect(read('web/src/opscenter/app.css')).toMatch(/\.oc-app \{[^}]*overflow: hidden;/);
  });

  test('the screen itself carries no left gutter for the dock width to add to', () => {
    expect(read('client/css/home-bar.css')).toMatch(/#launchpad-screen \{[^}]*padding: 0 0 0 var\(--dock-offset/);
  });
});
