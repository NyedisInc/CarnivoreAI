/* and writes nothing */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, resolve, sep } from 'node:path';
import type { Plugin } from 'vite';

const ALLOWED_ROOT = `web${sep}src${sep}`;

export function isSvelteStyleRequest(id: string): boolean {
    return id.includes('?svelte&type=style');
}

const EXTENSIONS = ['', '.ts', '.js', '.svelte', '.json', `${sep}index.ts`];

export function walk(root: string): string[] {
    if (!existsSync(root)) return [];
    const out: string[] = [];
    const visit = (dir: string): void => {
        for (const name of readdirSync(dir)) {
            const full = join(dir, name);
            const info = statSync(full, { throwIfNoEntry: false });
            if (!info) continue;
            if (info.isDirectory()) visit(full);
            else if (info.isFile()) out.push(full.slice(root.length + 1));
        }
    };
    visit(root);
    return out;
}

export function entrySource(repo: string, widget: Record<string, any>): string {
    const cell = JSON.stringify(join(repo, widget.paths.cell));
    const fixtures = JSON.stringify(join(repo, widget.paths.fixtures));
    return [
        `import Cell from ${cell};`,
        `import { ${widget.fixtures_export} } from ${fixtures};`,
        `import { registerDraftWidget } from './draft-register';`,
        `export function registerDrafts(): void {`,
        `    registerDraftWidget({ spec: ${JSON.stringify(widget)}, component: Cell, fixtures: ${widget.fixtures_export} });`,
        `}`,
        '',
    ].join('\n');
}

export function draftOverlay(draftDir: string, repo: string): Plugin {
    const mirror = join(draftDir, 'files');
    const files = new Map<string, string>();
    for (const rel of walk(mirror)) {
        if (!rel.startsWith(ALLOWED_ROOT) || rel.split(sep).includes('..')) throw new Error(`draft file outside web/src/: ${rel}`);
        files.set(resolve(repo, rel), join(mirror, rel));
    }
    const recordPath = join(draftDir, 'draft.json');
    const record = JSON.parse(readFileSync(recordPath, 'utf8')) as { kind: string };
    const entry = resolve(repo, 'web', 'src', 'widget-harness', 'draft-entry.ts');
    const widget = record.kind === 'new' ? (JSON.parse(readFileSync(join(draftDir, 'widget.json'), 'utf8')) as Record<string, any>) : null;

    const find = (abs: string): [string, string] | null => {
        for (const ext of EXTENSIONS) {
            const hit = files.get(abs + ext);
            if (hit) return [abs + ext, hit];
        }
        return null;
    };

    return {
        name: 'widget-lab-draft-overlay',
        enforce: 'pre',
        resolveId(source: string, importer?: string) {
            if (isSvelteStyleRequest(source)) return null;
            const clean = source.split('?')[0]!;
            const abs = clean.startsWith('.') && importer ? resolve(dirname(importer.split('?')[0]!), clean) : clean;
            return find(abs)?.[0] ?? null;
        },
        load(id: string) {
            if (isSvelteStyleRequest(id)) return null;
            const path = id.split('?')[0]!;
            if (widget && path === entry) return entrySource(repo, widget);
            const hit = files.get(path);
            return hit ? readFileSync(hit, 'utf8') : null;
        },
    };
}
