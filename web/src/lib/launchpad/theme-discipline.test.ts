import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

/** Repo root, four levels up from web/src/lib/launchpad. */
const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url));

const SLICE_FILES = [
    'web/src/lib/Glyph.svelte',
    'web/src/lib/launchpad/running-actions.ts',
    'web/src/lib/launchpad/running-host.ts',
    'web/src/lib/launchpad/ModalShell.svelte',
    'web/src/lib/launchpad/ChoiceModal.svelte',
    'web/src/lib/launchpad/CloneModal.svelte',
    'web/src/lib/launchpad/EditProjectModal.svelte',
    'web/src/lib/launchpad/ProjectFolderModal.svelte',
    'web/src/lib/launchpad/ProjectNameModal.svelte',
    'web/src/lib/launchpad/project-folder.ts',
    'web/src/lib/launchpad/create-flow.ts',
    'web/src/lib/launchpad/create-host.ts',
    'web/src/lib/launchpad/entry-flows.ts',
    'web/src/lib/launchpad/open-folder-flow.ts',
    'web/src/lib/launchpad/project-actions.ts',
    'web/src/lib/launchpad/modals.ts',
    'web/src/lib/launchpad/modal-types.ts',
    'web/src/lib/launchpad/home-screen-host.ts',
    'web/src/lib/launchpad/home-anchors.ts',
    'web/src/lib/launchpad/navigation.ts',
    'web/src/lib/launchpad/nav-host.ts',
    'web/src/lib/launchpad/deep-link.ts',
    'web/src/lib/launchpad/status-report.ts',
    'web/src/lib/launchpad/shim.ts',
];

const CHROME_FILES = new Set([
    // and the three
    'web/src/lib/launchpad/home-screen-host.ts',
    'web/src/lib/launchpad/home-anchors.ts',
    'web/src/lib/launchpad/status-report.ts',
    'web/src/lib/launchpad/nav-host.ts',
]);

function code(src: string): string {
    return src
        .replace(/<!--[\s\S]*?-->/g, ' ')
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/^[ \t]*\/\/.*$/gm, ' ');
}

function read(rel: string): string {
    return code(fs.readFileSync(path.join(repoRoot, rel), 'utf8'));
}

describe('no component in this slice paints a theme', () => {
    test.each(SLICE_FILES)('%s does not call applyTheme', (rel) => {
        expect(read(rel)).not.toContain('applyTheme');
    });

    test.each(SLICE_FILES)('%s does not reach the theme layer at all', (rel) => {
        const src = read(rel);
        expect(src).not.toContain('Themes');
        expect(src).not.toContain('ThemeNavigation');
        expect(src).not.toContain('data-theme');
        expect(src).not.toContain('setTheme');
    });

    test('and none of them writes to documentElement or body', () => {
        for (const rel of SLICE_FILES) {
            const src = read(rel);
            expect(src, rel).not.toContain('documentElement');
            expect(src, rel).not.toContain('document.body');
        }
    });

    test('NEGATIVE CONTROL: the scanner DOES find the call when it is there', () => {
        // A guard nobody has watched fail is a guard nobody has tested.
        expect(code("Themes.applyTheme('gruvbox');")).toContain('applyTheme');
        expect(code('// never call Themes.applyTheme here')).not.toContain('applyTheme');
        expect(code('<!-- no applyTheme on mount -->')).not.toContain('applyTheme');
    });
});

describe('no component inlines its own status dot', () => {
    const LED_COMPONENT = 'SessionFace';

    test('the files that render a dot render it as the component', () => {
        for (const rel of [
            'web/src/lib/ledger/LedgerSessions.svelte',
            'web/src/lib/sessions-page/RowLed.svelte',
        ]) {
            expect(read(rel), rel).toContain(`<${LED_COMPONENT}`);
        }
    });

    test('and NOTHING in the slice writes the dot markup by hand', () => {
        for (const rel of SLICE_FILES) {
            const src = read(rel);
            expect(src, rel).not.toContain('status-dot--');
            expect(src, rel).not.toContain('ledStateFor');
            expect(src, rel).not.toContain('data-inner');
            expect(src, rel).not.toContain('data-outer');
        }
    });
});

describe('no component reaches into another component\'s DOM', () => {
    test('only the chrome control touches an element by id, and that is its job', () => {
        for (const rel of SLICE_FILES) {
            if (CHROME_FILES.has(rel)) continue;
            const src = read(rel);
            expect(src, rel).not.toContain('getElementById');
            expect(src, rel).not.toMatch(/document\s*\.\s*querySelector/);
            for (const match of src.matchAll(/([A-Za-z_$][\w$]*)\??\.querySelector(All)?\b/g)) {
                expect(src, `${rel}: ${match[1]}.querySelector`).toContain(
                    `bind:this={${match[1]}}`,
                );
            }
        }
        for (const rel of CHROME_FILES) {
            expect(read(rel), rel).toContain('getElementById');
        }
    });
});

describe('the list itself stays honest', () => {
    test('every listed file exists, and the list is not empty', () => {
        // A guard that silently scanned nothing would pass forever. The
        expect(SLICE_FILES.length).toBeGreaterThanOrEqual(24);
        for (const rel of SLICE_FILES) {
            expect(fs.existsSync(path.join(repoRoot, rel)), rel).toBe(true);
        }
    });

    test('and every .svelte file in this slice IS on the list', () => {
        const dir = path.join(repoRoot, 'web/src/lib/launchpad');
        const components = fs.readdirSync(dir)
            .filter((f) => f.endsWith('.svelte'))
            .map((f) => `web/src/lib/launchpad/${f}`);
        const listed = new Set(SLICE_FILES);
        for (const rel of components) {
            expect(listed.has(rel), `${rel} is not covered by the theme guard`).toBe(true);
        }
    });
});
