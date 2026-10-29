/** @vitest-environment jsdom */
import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRATCH_MAX_AGE_MS = 60 * 60 * 1000;

function confineVitestTmp(): void {
    const scratch = join(dirname(fileURLToPath(import.meta.url)), 'node_modules', '.vitest-tmp');
    mkdirSync(scratch, { recursive: true });
    const cutoff = Date.now() - SCRATCH_MAX_AGE_MS;
    for (const name of readdirSync(scratch)) {
        const entry = join(scratch, name);
        try {
            if (statSync(entry).mtimeMs < cutoff) rmSync(entry, { recursive: true, force: true });
        } catch (err) {
            if ((err as NodeJS.ErrnoException).code !== 'ENOENT') throw err;
        }
    }
    process.env.TMPDIR = scratch;
}

confineVitestTmp();

export default defineConfig({
    plugins: [svelte({ hot: false })],
    resolve: { conditions: ['browser'] },
    server: { fs: { allow: ['..'] } },
    test: {
        fsModuleCache: true,
        environment: 'node',
        include: ['src/**/*.test.ts'],
        setupFiles: ['src/cplugs/huddle/task-manager-test-setup.ts'],
        reporters: ['default'],
    },
});
