import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import catalog from '../../../../../client/js/i18n/catalog.en.js';
import { registeredKey } from '../../../lib/menu-keys/menu-keys';
import { CORE_MANIFESTS } from '../core-manifests';
import type { WidgetDefinition } from './define-widget.svelte';
import { KNOWN, KNOWN_CEILING } from './shell-rules';
import { scanShell } from './shell-scan';
import { rememberedNames } from './widget-state.svelte';

const CELLS = fileURLToPath(new URL('../../cells', import.meta.url));
const DRAFT_ROOT = process.env['SHELL_CONFORMANCE_ROOT'] ?? '';

const foldersOf = (root: string): string[] =>
  fs.readdirSync(root, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();

function cellText(root: string, folder: string): string | null {
  const file = path.join(root, folder, 'Cell.svelte');
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
}

const isDefinition = (value: unknown): value is WidgetDefinition =>
  !!value && typeof value === 'object' && 'id' in value && 'scope' in value && 'actions' in value && 'state' in value;

function definitionFindings(def: WidgetDefinition): string[] {
  const out: string[] = [];
  const manifest = CORE_MANIFESTS[def.id];
  if (!manifest) return [`${def.id}: no such manifest`];
  const scope = manifest.scope === 'session' ? 'session' : 'global';
  if (def.scope !== scope) out.push(`${def.id}: declares scope ${def.scope}, its manifest is ${scope}`);
  for (const action of def.actions) {
    if (!registeredKey(action.id)) out.push(`${def.id}: action ${action.id} has no letter in client/js/menu-keys.js LETTERS`);
    if (!(action.labelKey in (catalog as Record<string, string>))) out.push(`${def.id}: ${action.labelKey} is not in the catalog`);
  }
  for (const [key, fallback] of Object.entries(def.settings)) {
    const field = manifest.settings?.fields[key];
    if (!field) out.push(`${def.id}: setting ${key} is not a manifest field`);
    else if (field.default !== fallback) out.push(`${def.id}: setting ${key} defaults to ${String(fallback)}, the manifest to ${String(field.default)}`);
  }
  if (rememberedNames(def.state).some((name) => !/^[a-z][a-z0-9-]*$/.test(name))) out.push(`${def.id}: a state name is not flat lowercase`);
  return out;
}

describe.skipIf(DRAFT_ROOT !== '')('every shipped cell renders through the widget shell, or is KNOWN', () => {
  const scans = foldersOf(CELLS).map((folder) => ({ folder, rules: scanShell(cellText(CELLS, folder)) }));
  const known = new Set(KNOWN.map((entry) => entry.folder));

  it('looked at the cells (a scan of nothing is not a pass)', () => {
    expect(scans.length).toBeGreaterThan(30);
    expect(scans.find((one) => one.folder === 'notes')?.rules).toEqual([]);
  });

  it('has no unmigrated cell outside KNOWN (a new cell is never added to KNOWN)', () => {
    const bad = scans.filter((one) => one.rules.length && !known.has(one.folder)).map((one) => `${one.folder}: ${one.rules.join(', ')}`);
    expect(bad, 'see docs/widget-spec.md section 13').toEqual([]);
  });

  it('keeps every KNOWN row true (a migrated cell leaves the table)', () => {
    const stale = KNOWN.filter((entry) => {
      const scan = scans.find((one) => one.folder === entry.folder);
      return !scan || scan.rules.length === 0;
    }).map((entry) => entry.folder);
    expect(stale).toEqual([]);
  });

  it('only shrinks: KNOWN stays at or under its ceiling, one row per folder, each naming its issue', () => {
    expect(KNOWN.length).toBeLessThanOrEqual(KNOWN_CEILING);
    expect(known.size).toBe(KNOWN.length);
    expect(KNOWN.filter((entry) => !/^#\d+/.test(entry.why))).toEqual([]);
  });

  it('every migrated definition agrees with its manifest, the letter registry and the catalog', async () => {
    const modules = import.meta.glob('../../cells/*/Cell.svelte');
    const migrated = scans.filter((one) => one.rules.length === 0).map((one) => one.folder);
    expect(migrated).toEqual(expect.arrayContaining(['notes', 'tasks', 'tasks-all']));
    const findings: string[] = [];
    for (const folder of migrated) {
      const load = modules[`../../cells/${folder}/Cell.svelte`];
      const mod = load ? ((await load()) as Record<string, unknown>) : {};
      const defs = Object.values(mod).filter(isDefinition);
      if (defs.length !== 1) findings.push(`${folder}: exports ${defs.length} definitions, wants 1`);
      defs.forEach((def) => findings.push(...definitionFindings(def)));
    }
    expect(findings).toEqual([]);
  }, Number.POSITIVE_INFINITY);
});

describe.runIf(DRAFT_ROOT !== '')('a Widget Lab draft renders through the widget shell (no waivers)', () => {
  it('has no finding', () => {
    const bad = foldersOf(DRAFT_ROOT).flatMap((folder) => scanShell(cellText(DRAFT_ROOT, folder)).map((rule) => `${folder}: ${rule}`));
    expect(bad, 'see docs/widget-spec.md section 13').toEqual([]);
  });
});

describe('each rule goes red on a broken cell and stays green on a conforming one', () => {
  const GOOD = `<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';
  export const W = defineWidget({ id: 'core.x', scope: 'global', actions: [], state: {} });
</script>
<script lang="ts">
  const widget = useWidget(W, () => props);
</script>
<WidgetShell {widget}><p>body</p></WidgetShell>`;

  it('the conforming cell has no finding', () => {
    expect(scanShell(GOOD)).toEqual([]);
  });
  it('a cell with no shell, no definition, no binding breaks each rule', () => {
    expect(scanShell('<script lang="ts">let x = 1;</script><div>{x}</div>')).toEqual(['no-definition', 'no-state', 'no-binding', 'no-shell']);
    expect(scanShell(null)).toEqual(['no-cell']);
  });
  it('a definition that does not declare its state is not migrated', () => {
    expect(scanShell(GOOD.replace(', state: {}', ''))).toEqual(['no-state']);
  });
  it('a definition outside the module script, or a binding inside it, does not count', () => {
    const inline = GOOD.replace('<script lang="ts" module>', '<script lang="ts">');
    expect(scanShell(inline)).toContain('no-definition');
    expect(scanShell(GOOD.replace('const widget = useWidget(W, () => props);', ''))).toEqual(['no-binding']);
  });
  it('a definition that disagrees with its manifest, uses an unlettered id or a missing key is named', () => {
    const bad: WidgetDefinition = { id: 'core.notes', scope: 'global', actions: [{ id: 'frobnicate', labelKey: 'no.such.key' }], settings: { nope: true }, state: {} };
    expect(definitionFindings(bad)).toEqual([
      'core.notes: declares scope global, its manifest is session',
      'core.notes: action frobnicate has no letter in client/js/menu-keys.js LETTERS',
      'core.notes: no.such.key is not in the catalog',
      'core.notes: setting nope is not a manifest field',
    ]);
  });
});
