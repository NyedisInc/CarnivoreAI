import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { codeOnly, scanCell, scanCellData, type CellSource, type DataFinding, type MenuFinding } from './cell-menu-scan';
import { ALLOWED, DATA_KNOWN, DATA_KNOWN_CEILING, KNOWN, excusedRules } from './menu-rules';

const CELLS = fileURLToPath(new URL('../../cells', import.meta.url));
const DRAFT_ROOT = process.env['MENU_CONFORMANCE_ROOT'] ?? '';

function sourcesOf(dir: string, base = ''): CellSource[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'fixtures' ? [] : sourcesOf(full, path.join(base, entry.name));
    if (!/\.(svelte|ts)$/.test(entry.name) || /\.test\.|\.spec\./.test(entry.name)) return [];
    return [{ path: path.join(base, entry.name), text: fs.readFileSync(full, 'utf8') }];
  });
}

function foldersOf(root: string): string[] {
  return fs.readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
}

const say = (folder: string, f: MenuFinding): string => `${folder}/${f.path}:${f.line} ${f.rule}: ${f.detail}`;

const sayData = (folder: string, f: DataFinding): string => `${folder}/${f.path}:${f.line} ${f.rule}: ${f.detail}`;

describe.skipIf(DRAFT_ROOT !== '')('every shipped widget cell meets the data standard (no fetch, no timer of its own)', () => {
  const scans = foldersOf(CELLS).map((folder) => ({ folder, findings: scanCellData(sourcesOf(path.join(CELLS, folder))) }));

  it('has no finding outside DATA_KNOWN (a new cell is never added to it)', () => {
    const bad = scans.flatMap(({ folder, findings }) =>
      findings.filter((f) => !DATA_KNOWN.some((row) => row.folder === folder && row.file === f.path && row.rule === f.rule)).map((f) => sayData(folder, f)));
    expect(bad, 'a cell reads a shared store: docs/widget-spec.md section 14, rule 6').toEqual([]);
  });

  it('keeps every DATA_KNOWN row true (a fixed cell leaves the list) and the ceiling equals its length', () => {
    const stale = DATA_KNOWN.filter((row) => !scans.some((one) => one.folder === row.folder && one.findings.some((f) => f.path === row.file && f.rule === row.rule)));
    expect(stale).toEqual([]);
    expect(DATA_KNOWN.length).toBe(DATA_KNOWN_CEILING);
  });
});

describe.skipIf(DRAFT_ROOT !== '')('every shipped widget cell meets the menu standard', () => {
  const scans = foldersOf(CELLS).map((folder) => ({ folder, findings: scanCell(sourcesOf(path.join(CELLS, folder))) }));

  it('looked at the cells (a scan of nothing is not a pass)', () => {
    expect(scans.length).toBeGreaterThan(20);
    expect(scans.find((one) => one.folder === 'notes')).toBeDefined();
  });

  it('has no finding outside ALLOWED and KNOWN', () => {
    const bad = scans.flatMap(({ folder, findings }) => findings.filter((f) => !excusedRules(folder).has(f.rule)).map((f) => say(folder, f)));
    expect(bad, 'see docs/widget-spec.md section 11; a new cell is never added to KNOWN').toEqual([]);
  });

  it('keeps every ALLOWED and KNOWN row true (a fixed cell leaves the table)', () => {
    const stale = [...ALLOWED, ...KNOWN].flatMap((entry) => {
      const scan = scans.find((one) => one.folder === entry.folder);
      if (!scan) return [`${entry.folder}: no such cell folder`];
      return entry.rules.filter((rule) => !scan.findings.some((f) => f.rule === rule)).map((rule) => `${entry.folder}: ${rule} no longer found`);
    });
    expect(stale).toEqual([]);
  });

  it('names an issue for every KNOWN row and a ruling for every ALLOWED row', () => {
    expect(KNOWN.filter((entry) => !/^#\d+$/.test(entry.why))).toEqual([]);
    expect(ALLOWED.filter((entry) => !/Joe \(ccsliinc\)|declared/.test(entry.why))).toEqual([]);
  });

  it('passes the references: Notes (chrome) and Themes (declared controls)', () => {
    expect(scans.find((one) => one.folder === 'notes')!.findings).toEqual([]);
    expect(scans.find((one) => one.folder === 'themes')!.findings).toEqual([]);
  });
});

describe.runIf(DRAFT_ROOT !== '')('a Widget Lab draft meets the menu standard (no waivers)', () => {
  it('has no finding', () => {
    const bad = foldersOf(DRAFT_ROOT).flatMap((folder) => [
      ...scanCell(sourcesOf(path.join(DRAFT_ROOT, folder))).map((f) => say(folder, f)),
      ...scanCellData(sourcesOf(path.join(DRAFT_ROOT, folder))).map((f) => sayData(folder, f)),
    ]);
    expect(bad, 'see docs/widget-spec.md section 11').toEqual([]);
  });
});

describe('each rule goes red on a broken cell and stays green on a conforming one', () => {
  const KEBAB_CELL = `<script lang="ts">
  import CascadeMenu from '../../../lib/drawer-tabs/CascadeMenu.svelte';
  let anchor = $state<HTMLElement | null>(null);
</script>
<div class="bar">
  <button type="button" aria-haspopup="menu" onclick={(e) => (anchor = e.currentTarget as HTMLElement)}>more</button>
  {#if anchor}<CascadeMenu root={[]} {anchor} label="options" onClose={() => (anchor = null)} />{/if}
</div>`;
  const GOOD = `<script lang="ts">
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  $effect(() => declareWidgetActions(hostId, 'draft', []));
</script>
<!-- a comment with aria-haspopup="menu" is not a button -->
<div role="radiogroup">{#each SCOPES as one (one)}<button type="button" role="radio" aria-checked={x === one} onclick={() => pick(one)}>{one}</button>{/each}</div>
<ul>
  {#each items as item (item.id)}
    <li><button type="button" onclick={() => open(item)}>{item.name}</button></li>
  {/each}
</ul>`;

  const rulesOf = (sources: CellSource[]): string[] => [...new Set(scanCell(sources).map((f) => f.rule))].sort();

  it('a body kebab with a private CascadeMenu breaks two rules', () => {
    expect(rulesOf([{ path: 'Cell.svelte', text: KEBAB_CELL }])).toEqual(['body-menu-button', 'menu-without-declared-actions']);
  });
  it('a kebab icon or a dots glyph is a menu button too', () => {
    expect(rulesOf([{ path: 'Cell.svelte', text: '<button type="button" onclick={go}><Icon name="kebab" size={14} /></button>' }])).toEqual(['body-menu-button']);
    expect(rulesOf([{ path: 'Cell.svelte', text: '<button type="button" class="m">⋮</button>' }])).toEqual(['body-menu-button']);
  });
  it('clickable rows with no menu are fine: a row has no menu of its own (Joe (ccsliinc), item 1030 message 5597)', () => {
    expect(scanCell([{ path: 'FxRowView.svelte', text: '<div class="fx-row" role="treeitem" tabindex="-1" onclick={() => onActivate(row)}>{row.name}</div>' }])).toEqual([]);
  });
  it('the conforming cell (declared actions, a radio set, rows that only click) has no finding', () => {
    expect(scanCell([{ path: 'Cell.svelte', text: GOOD }])).toEqual([]);
  });
  it('a declared menu still may not draw a body kebab', () => {
    const declared = KEBAB_CELL.replace('</script>', "  $effect(() => declareWidgetActions(id, 'x', []));\n</script>");
    expect(rulesOf([{ path: 'Cell.svelte', text: declared }])).toEqual(['body-menu-button']);
  });
});

describe('the data rule goes red on a cell that fetches or keeps a timer, and stays green on one that reads a store', () => {
  const rules = (text: string, file = 'Cell.svelte'): string[] => scanCellData([{ path: file, text }]).map((f) => f.rule);

  it('setInterval in a script is a data-interval, authFetch and fetch are data-fetch', () => {
    expect(rules('<script lang="ts">const t = setInterval(() => (now = Date.now()), 30_000);</script>')).toEqual(['data-interval']);
    expect(rules('<script lang="ts">async function load() { return authFetch("/api/v1/x"); }</script>')).toEqual(['data-fetch']);
    expect(rules('export const load = () => window.fetch("/x");', 'load.ts')).toEqual(['data-fetch']);
  });
  it('comments, strings, markup text and another object\'s method named fetch are not calls', () => {
    expect(rules('<script lang="ts">// setInterval(x)\n/* fetch(y) */ const s = "authFetch(z)"; store.fetch(a);</script><p>don\'t fetch(it)</p>')).toEqual([]);
  });
  it('the line number is the call\'s line', () => {
    expect(scanCellData([{ path: 'a.ts', text: 'const a = 1;\n\nsetInterval(a, 5);' }])[0]?.line).toBe(3);
    expect(codeOnly('// fetch(x)\nfetch(\'a\')')).toBe('           \nfetch(\' \')');
  });
});
