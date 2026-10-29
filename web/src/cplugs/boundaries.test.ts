import { describe, expect, test } from 'vitest';
import { BUILTIN_CPLUGS } from './builtin';
import { POPOUT_CPLUGS } from './popout';

const SOURCES = import.meta.glob('./*/**/*.{ts,svelte}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const HOST = new Set(['sdk', 'host']);

function specifiers(source: string): string[] {
  const out: string[] = [];
  for (const m of source.matchAll(/(?:import|export)\s[^'"`;]*?from\s+['"]([^'"]+)['"]|import\s+['"]([^'"]+)['"]/g)) out.push(m[1] ?? m[2] ?? '');
  return out;
}

function resolveFrom(file: string, spec: string): string {
  const parts = file.split('/').slice(0, -1);
  for (const part of spec.split('/')) {
    if (part === '..') parts.pop();
    else if (part !== '.') parts.push(part);
  }
  return parts.join('/');
}

export function violations(file: string, source: string): string[] {
  const id = file.split('/')[1] ?? '';
  return specifiers(source).filter((spec) => {
    if (spec === 'svelte' || spec.startsWith('svelte/')) return false;
    if (!spec.startsWith('.')) return true;
    const target = resolveFrom(file, spec);
    if (target === `./${id}` || target.startsWith(`./${id}/`) || target === './sdk' || target.startsWith('./sdk/')) return false;
    return target !== `src/cplugs/${id}/cplug.json`;
  });
}

const BOUNDARY_KNOWN: readonly string[] = [
  './huddle/TaskManagerProjectHead.svelte -> ../../lib/motion/motion',
  './huddle/ask/TaskManagerAskForm.svelte -> ../../../opscenter/ui/Icon.svelte',
  './huddle/ask/ask-state.svelte.ts -> ../../../lib/outbox/outbox',
  './huddle/huddle.svelte.ts -> ../../lib/outbox/outbox',
  './huddle/index.ts -> ../../lib/swarm-switch/control.svelte',
  './huddle/session-roles-action.ts -> ../../lib/plugins/types',
  './huddle/swarm/characters/clock.ts -> ../../../../lib/motion/animation-types',
  './huddle/swarm/characters/clock.ts -> ../../../../lib/motion/motion',
  './huddle/swarm/characters/reduced-motion.svelte.ts -> ../../../../lib/motion/motion',
  './huddle/swarm/tier-drag.ts -> ../../../lib/motion/motion',
  './huddle/task-manager-snapshot.ts -> ../../lib/data-cache/cache',
  './huddle/task-manager-tab.ts -> ../../lib/swarm-switch/control.svelte',
];

const BOUNDARY_KNOWN_CEILING = 12;

describe('plugin boundaries', () => {
  const files = Object.keys(SOURCES).filter((f) => !HOST.has(f.split('/')[1] ?? '') && !f.endsWith('.test.ts'));
  const found = files.flatMap((f) => violations(f, SOURCES[f] ?? '').map((spec) => `${f} -> ${spec}`));

  test('every plugin module imports only the sdk, itself, its manifest and svelte', () => {
    expect(files.some((f) => f.startsWith('./huddle/'))).toBe(true);
    expect(found.filter((one) => !BOUNDARY_KNOWN.includes(one)), 'import through the plugin sdk; never add to BOUNDARY_KNOWN').toEqual([]);
  });

  test('every BOUNDARY_KNOWN row is still true, and the list only shrinks', () => {
    expect(BOUNDARY_KNOWN.filter((one) => !found.includes(one))).toEqual([]);
    expect(BOUNDARY_KNOWN.length).toBe(BOUNDARY_KNOWN_CEILING);
  });

  test('the check can fail', () => {
    expect(violations('./huddle/x.ts', "import { t } from '../../lib/i18n/index.svelte';\nimport x from '../other/y';\n"))
      .toEqual(['../../lib/i18n/index.svelte', '../other/y']);
    expect(violations('./huddle/chat/x.ts', "import a from '../../sdk';\nimport b from '../huddle-model';\nimport c from '../../../lib/x';\n")).toEqual(['../../../lib/x']);
    expect(violations('./huddle/x.ts', "import { t } from '../sdk';\nimport A from './A.svelte';\nimport { mount } from 'svelte';\n")).toEqual([]);
  });

  test('each manifest matches its web part and both ship lists agree', () => {
    for (const cplug of BUILTIN_CPLUGS) {
      expect(cplug.id).toBe(cplug.manifest.id);
      expect(cplug.manifest.id).toMatch(/^[a-z][a-z0-9]{1,23}$/);
      expect((cplug.tabs ?? []).map((d) => d.id).sort()).toEqual([...(cplug.manifest.surfaces.tabs ?? [])].sort());
      expect((cplug.menuLinks ?? []).map((l) => l.id).sort()).toEqual([...(cplug.manifest.surfaces.menu_links ?? [])].sort());
      for (const tab of cplug.tabs ?? []) {
        expect(tab.labelKey.startsWith(`cplug.${cplug.id}.`)).toBe(true);
        expect(tab.id === cplug.id || tab.id.startsWith(`${cplug.id}-`)).toBe(true);
      }
      const popout = POPOUT_CPLUGS.find((p) => p.id === cplug.id);
      const declared = (cplug.tabs ?? []).filter((d) => d.popout === true).map((d) => d.id);
      expect(popout?.tabs.map((d) => d.id) ?? []).toEqual(declared);
    }
  });
});
