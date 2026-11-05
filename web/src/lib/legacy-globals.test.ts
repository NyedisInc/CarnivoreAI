import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { describe, expect, test } from 'vitest';

const SRC = join(__dirname, '..');
const SEAM = 'lib/legacy-globals.ts';

export const WINDOW_CAST = /\b(?:window|hostWindow\(\)|globalThis)\)?\s+as\s+unknown\s+as\b/g;

const WINDOW_CAST_KNOWN: readonly string[] = [
  'admin/App.svelte x1',
  'cplugs/huddle/style-guide/CharacterBoard.svelte x1',
  'cplugs/huddle/style-guide/ExpressionBoard.svelte x1',
  'cplugs/huddle/style-guide/SwarmPageBoard.svelte x1',
  'cplugs/huddle/style-guide/SwarmPanelBoard.svelte x1',
  'cplugs/huddle/swarm/swarm-settings.svelte.ts x1',
  'cplugs/sdk/floor.svelte.ts x1',
  'cplugs/sdk/sessions.svelte.ts x1',
  'lib/add-to-menu/host.ts x1',
  'lib/automations/schedule-prefill.ts x3',
  'lib/browser/center-nav.ts x1',
  'lib/browser/select-push.svelte.ts x1',
  'lib/byoai/audio.ts x1',
  'lib/carnivore-account/account-page-host.ts x1',
  'lib/catalog/catalog.ts x1',
  'lib/conversation-open/open.ts x1',
  'lib/drawer/env.ts x2',
  'lib/elite/engine/modem.ts x2',
  'lib/first-run/boot.ts x1',
  'lib/first-run/join-api.ts x1',
  'lib/item-menu/menus/row-items.ts x1',
  'lib/item-menu/menus/row.ts x1',
  'lib/item-menu/open.svelte.ts x1',
  'lib/item-menu/row-context.ts x1',
  'lib/item-menu/row-open.ts x1',
  'lib/item-menu/row-plugins.ts x1',
  'lib/item-menu/row-test-env.ts x1',
  'lib/launchpad/create-host.ts x2',
  'lib/launchpad/nav-generation.ts x1',
  'lib/launchpad/nav-host.ts x3',
  'lib/launchpad/recent-actions.ts x4',
  'lib/launchpad/running-host.ts x1',
  'lib/launchpad/shim.ts x1',
  'lib/listing-push/boot.ts x1',
  'lib/native-shell/shell.ts x1',
  'lib/notes-header/mount-notes.ts x1',
  'lib/notifications/presence.ts x1',
  'lib/notifications/screen-filter.ts x2',
  'lib/open-files/codemirror.ts x1',
  'lib/project-colors/ProjectColorPopover.svelte x1',
  'lib/resource-push/boot.ts x1',
  'lib/sessions-search/host.ts x1',
  'lib/sessions/poller.ts x2',
  'lib/sessions/session-label.ts x1',
  'lib/sessions/store.svelte.ts x1',
  'lib/sidebar-shell/row-globals.ts x1',
  'lib/sidebar-shell/shell.svelte.ts x1',
  'lib/terminal-foot-bar/mount-terminal-foot.ts x2',
  'lib/terminal-provider/publish.ts x1',
  'lib/terminal-search/prompt-header-harness.ts x2',
  'lib/terminal-search/search-host.ts x1',
  'lib/user-guide/sidebar-legend.ts x1',
  'opscenter/cells/terminal-live/row-menu.ts x2',
  'opscenter/engine/primary-bind.ts x1',
  'opscenter/lib/shift-held.svelte.ts x1',
  'widget-harness/idle-run.ts x2',
];

const WINDOW_CAST_KNOWN_CEILING = 58;

export function countWindowCasts(text: string): number {
  return (text.match(WINDOW_CAST) ?? []).length;
}

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) sourceFiles(full, out);
    else if (/\.(ts|svelte)$/.test(name) && !/\.test\.ts$/.test(name)) out.push(relative(SRC, full).split(sep).join('/'));
  }
  return out;
}

function findCasts(): Map<string, number> {
  const found = new Map<string, number>();
  for (const file of sourceFiles(SRC)) {
    if (file === SEAM) continue;
    const n = countWindowCasts(readFileSync(join(SRC, file), 'utf8'));
    if (n > 0) found.set(file, n);
  }
  return found;
}

function known(): Map<string, number> {
  return new Map(WINDOW_CAST_KNOWN.map((row) => {
    const [file, count] = row.split(' x');
    return [file as string, Number(count)] as [string, number];
  }));
}

describe('legacy window globals go through legacy-globals.ts', () => {
  test('the scan can go red: it sees a multi-line cast and ignores a typed read', () => {
    expect(countWindowCasts('(window as unknown as {\n A: 1 }).A')).toBe(1);
    expect(countWindowCasts('(hostWindow() as unknown as X | undefined)?.Y')).toBe(1);
    expect(countWindowCasts('const w = hostWindow(); w?.API')).toBe(0);
  });

  test('no file outside the seam casts the window beyond its KNOWN row', () => {
    const allowed = known();
    const over = [...findCasts()].filter(([file, n]) => n > (allowed.get(file) ?? 0));
    expect(over, 'use legacyGlobal/legacyApi/legacyAuth/sessionSidebar from lib/legacy-globals.ts; never add to WINDOW_CAST_KNOWN').toEqual([]);
  });

  test('every KNOWN row is still true, and the list only shrinks', () => {
    const found = findCasts();
    const stale = [...known()].filter(([file, n]) => (found.get(file) ?? 0) !== n);
    expect(stale, 'lower or delete the row of a migrated file').toEqual([]);
    expect(WINDOW_CAST_KNOWN.length).toBeLessThanOrEqual(WINDOW_CAST_KNOWN_CEILING);
  });
});
