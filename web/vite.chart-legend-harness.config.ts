import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export default defineConfig({
    plugins: [svelte(), tailwindcss()],
    build: {
        outDir: process.env.HARNESS_OUT ?? mkdtempSync(join(tmpdir(), 'chart-legend-harness-')),
        emptyOutDir: true,
        minify: false,
        target: 'es2022',
        cssCodeSplit: false,
        rollupOptions: {
            input: fileURLToPath(new URL('./src/test-harness/chart-legend/chart-legend-harness.ts', import.meta.url)),
            output: {
                entryFileNames: 'harness.js',
                assetFileNames: (info) => (info.names?.some((n) => n.endsWith('.css')) ? 'harness.css' : 'asset-[name][extname]'),
            },
        },
    },
});
