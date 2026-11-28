import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import { walkSources } from '../test-support/source-scan';
import { BUILTIN_CPLUGS } from './builtin';
import { POPOUT_CPLUGS } from './popout';

const SCRIPTS = import.meta.glob('./*/**/*.{ts,svelte}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const STYLES = Object.fromEntries(
  walkSources(__dirname, /\.css$/).map((rel) => [`./${rel}`, fs.readFileSync(path.join(__dirname, rel), 'utf8')]),
);
const SOURCES: Record<string, string> = { ...SCRIPTS, ...STYLES };
const CPLUG_UI = import.meta.glob('../lib/cplug-ui/**/*.{ts,svelte}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const HOST = new Set(['sdk', 'host']);
const CPLUGS_DIR = 'plugins';

const SPECIFIER =
  /(?:import|export)\s[^'"`;]*?from\s+['"]([^'"]+)['"]|(?<![@\w])import\s+['"]([^'"]+)['"]|\bimport\s*\(\s*['"`]([^'"`]+)['"`]\s*\)|@import\s+(?:url\(\s*)?['"]([^'"]+)['"]/g;

export function specifiers(source: string): string[] {
  const out: string[] = [];
  for (const m of source.matchAll(SPECIFIER)) out.push(m[1] ?? m[2] ?? m[3] ?? m[4] ?? '');
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
    return target !== `src/plugins/${id}/carnivore.toml`;
  });
}

const BOUNDARY_KNOWN: readonly string[] = [
  './taskmanager/TaskManagerProjectHead.svelte -> ../../lib/motion/motion',
  './taskmanager/index.ts -> ../../lib/swarm-switch/control.svelte',
  './taskmanager/swarm/characters/clock.ts -> ../../../../lib/motion/animation-types',
  './taskmanager/swarm/characters/clock.ts -> ../../../../lib/motion/motion',
  './taskmanager/swarm/characters/reduced-motion.svelte.ts -> ../../../../lib/motion/motion',
  './taskmanager/swarm/tier-drag.ts -> ../../../lib/motion/motion',
  './taskmanager/task-manager-snapshot.ts -> ../../lib/data-cache/cache',
  './taskmanager/task-manager-tab.ts -> ../../lib/swarm-switch/control.svelte',
];

const BOUNDARY_KNOWN_CEILING = 8;

const BOUNDARY_STYLE_KNOWN: readonly string[] = [
  './reviewboard/public/visitor-page/public.css -> ../../../../../../client/css/popup-focus.css',
  './reviewboard/public/visitor-page/public.css -> ../../../../lib/base/elements.css',
  './reviewboard/public/visitor-page/public.css -> ../../../../lib/base/icon-button.css',
  './reviewboard/public/visitor-page/public.css -> ../../../../lib/base/pick.css',
  './reviewboard/public/visitor-page/public.css -> ../../../../lib/base/segmented.css',
  './reviewboard/public/visitor-page/public.css -> ../../../../opscenter/focus.css',
  './reviewboard/public/visitor-page/public.css -> ../../../../opscenter/tokens.css',
];

const BOUNDARY_STYLE_KNOWN_CEILING = 7;

const PLATFORM_KNOWN: readonly string[] = [];

const PLATFORM_KNOWN_CEILING = 0;

function fromSrc(key: string): string {
  return key.startsWith('./') ? `${CPLUGS_DIR}/${key.slice(2)}` : key.slice(3);
}

export function platformViolations(file: string, source: string, features: ReadonlySet<string>): string[] {
  return specifiers(source).filter((spec) => {
    if (!spec.startsWith('.')) return false;
    const [top, folder] = resolveFrom(file, spec).split('/');
    return top === CPLUGS_DIR && features.has(folder ?? '');
  });
}

describe('platform section', () => {
  const features = new Set(Object.keys(SOURCES).map((f) => f.split('/')[1] ?? '').filter((id) => !HOST.has(id)));
  const platform = Object.entries({ ...SOURCES, ...CPLUG_UI })
    .map(([key, text]) => [fromSrc(key), text] as const)
    .filter(([file]) => (file.startsWith('plugins/sdk/') || file.startsWith('plugins/host/') || file.startsWith('lib/cplug-ui/')) && !file.endsWith('.test.ts'));
  const found = platform.flatMap(([file, text]) => platformViolations(file, text, features).map((spec) => `${file} -> ${spec}`));

  test('the platform imports no feature', () => {
    expect(platform.some(([file]) => file.startsWith('lib/cplug-ui/')) && platform.some(([file]) => file.startsWith('plugins/sdk/'))).toBe(true);
    expect(features.has('taskmanager')).toBe(true);
    expect(found.filter((one) => !PLATFORM_KNOWN.includes(one)), 'the platform never imports a feature; never add to PLATFORM_KNOWN').toEqual([]);
  });

  test('every PLATFORM_KNOWN row is still true, and the list only shrinks', () => {
    expect(PLATFORM_KNOWN.filter((one) => !found.includes(one))).toEqual([]);
    expect(PLATFORM_KNOWN.length).toBe(PLATFORM_KNOWN_CEILING);
  });

  test('the platform check can fail', () => {
    const ids = new Set(['huddle', 'flow']);
    expect(platformViolations('plugins/sdk/x.ts', "import a from '../huddle/y';\nimport b from './menu';\nimport { mount } from 'svelte';\n", ids)).toEqual(['../huddle/y']);
    expect(platformViolations('lib/cplug-ui/x.ts', "import a from '../../plugins/flow/flow-model';\nimport b from '../../plugins/sdk';\n", ids)).toEqual(['../../plugins/flow/flow-model']);
    expect(fromSrc('../lib/cplug-ui/api.ts')).toBe('lib/cplug-ui/api.ts');
    expect(fromSrc('./sdk/menu.ts')).toBe('plugins/sdk/menu.ts');
  });
});

describe('plugin boundaries', () => {
  const files = Object.keys(SOURCES).filter((f) => !HOST.has(f.split('/')[1] ?? '') && !f.endsWith('.test.ts') && !f.endsWith('/vite.bundle.config.ts'));
  const found = files.flatMap((f) => violations(f, SOURCES[f] ?? '').map((spec) => `${f} -> ${spec}`));

  const known = [...BOUNDARY_KNOWN, ...BOUNDARY_STYLE_KNOWN];

  test('every plugin module and sheet imports only the sdk, itself, its manifest and svelte', () => {
    expect(files.some((f) => f.startsWith('./taskmanager/'))).toBe(true);
    const sheets = files.filter((f) => f.endsWith('.css'));
    expect(sheets.length, 'the scan read no plugin stylesheet').toBeGreaterThan(5);
    expect(sheets.every((f) => (SOURCES[f] ?? '').length > 0), 'a plugin stylesheet read as empty').toBe(true);
    expect(found.filter((one) => !known.includes(one)), 'import through the plugin sdk; never add to a BOUNDARY list').toEqual([]);
  });

  test('every BOUNDARY_KNOWN and BOUNDARY_STYLE_KNOWN row is still true, and the lists only shrink', () => {
    expect(known.filter((one) => !found.includes(one))).toEqual([]);
    expect(BOUNDARY_KNOWN.length).toBe(BOUNDARY_KNOWN_CEILING);
    expect(BOUNDARY_STYLE_KNOWN.length).toBe(BOUNDARY_STYLE_KNOWN_CEILING);
  });

  test('the check can fail', () => {
    expect(violations('./taskmanager/x.ts', "import { t } from '../../lib/i18n/index.svelte';\nimport x from '../other/y';\n"))
      .toEqual(['../../lib/i18n/index.svelte', '../other/y']);
    expect(violations('./taskmanager/chat/x.ts', "import a from '../../sdk';\nimport b from '../huddle-model';\nimport c from '../../../lib/x';\n")).toEqual(['../../../lib/x']);
    expect(violations('./taskmanager/x.ts', "import { t } from '../sdk';\nimport A from './A.svelte';\nimport { mount } from 'svelte';\n")).toEqual([]);
    expect(violations('./taskmanager/x.ts', "import m from '../../../../src/plugins/taskmanager/carnivore.toml';\n")).toEqual([]);
    expect(violations('./taskmanager/x.ts', "import m from '../../../../src/plugins/taskmanager/cplug.json';\n"))
      .toEqual(['../../../../src/plugins/taskmanager/cplug.json']);
    expect(violations('./taskmanager/x.ts', "import m from '../../../../src/plugins/other/carnivore.toml';\n"))
      .toEqual(['../../../../src/plugins/other/carnivore.toml']);
  });

  test('the check sees a dynamic import and a stylesheet import (M10)', () => {
    expect(violations('./taskmanager/x.ts', "const m = await import('../../lib/motion/motion');\nconst own = await import(`./own`);\n"))
      .toEqual(['../../lib/motion/motion']);
    expect(violations('./taskmanager/a/x.css', "@import '../../../lib/base/pick.css';\n@import url(\"./own.css\");\n@import '../b.css';\n"))
      .toEqual(['../../../lib/base/pick.css']);
    expect(specifiers('const important = 1; // @importance\n')).toEqual([]);
  });

  test('each manifest matches its web part and both ship lists agree', () => {
    for (const cplug of BUILTIN_CPLUGS) {
      expect(cplug.id).toBe(cplug.manifest.id);
      expect(cplug.manifest.id).toMatch(/^[a-z][a-z0-9]{1,23}$/);
      const surfaces = cplug.manifest.surfaces ?? cplug.manifest.ui ?? {};
      expect((cplug.tabs ?? []).map((d) => d.id).sort()).toEqual([...(surfaces.tabs ?? [])].sort());
      expect((cplug.menuLinks ?? []).map((l) => l.id).sort()).toEqual([...(surfaces.menu_links ?? [])].sort());
      const old = cplug.manifest.renamed_from;
      const owners = [cplug.id, ...(old ? [old] : [])];
      const stringOwners = [cplug.id, ...(old && (cplug.manifest.renamed_from_keeps ?? []).includes('strings') ? [old] : [])];
      for (const tab of cplug.tabs ?? []) {
        expect(stringOwners.some((id) => tab.labelKey.startsWith(`cplug.${id}.`))).toBe(true);
        expect(owners.some((id) => tab.id === id || tab.id.startsWith(`${id}-`))).toBe(true);
      }
      const popout = POPOUT_CPLUGS.find((p) => p.id === cplug.id);
      const declared = (cplug.tabs ?? []).filter((d) => d.popout === true).map((d) => d.id);
      expect(popout?.tabs.map((d) => d.id) ?? []).toEqual(declared);
    }
  });
});
