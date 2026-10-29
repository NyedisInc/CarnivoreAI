/* the widget harness page */
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { join, resolve, sep } from 'node:path';
import { popupFocusLast } from './vite.widget-harness.shared';
import { draftOverlay } from './vite.widget-draft.plugin';

const root = fileURLToPath(new URL('./src/widget-harness', import.meta.url));
const repo = fileURLToPath(new URL('..', import.meta.url)).replace(/[/\\]$/, '');

const draftDir = process.env.LAB_DRAFT_DIR ? resolve(process.env.LAB_DRAFT_DIR) : '';
if (!draftDir) throw new Error('LAB_DRAFT_DIR is not set: this build needs a draft folder');
const outDir = join(draftDir, 'build', 'site');
if (!outDir.startsWith(draftDir + sep)) throw new Error('the draft build must write inside the draft folder');
const cacheDir = join(draftDir, 'build', '.vite-cache');

export default defineConfig({
    root,
    cacheDir,
    base: './',
    plugins: [draftOverlay(draftDir, repo), svelte(), tailwindcss(), popupFocusLast()],
    build: {
        outDir,
        emptyOutDir: true,
        minify: 'oxc',
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
        modulePreload: { polyfill: false },
        rollupOptions: {
            output: {
                entryFileNames: 'draft.js',
                chunkFileNames: 'draft-chunk-[name].js',
                assetFileNames: (info) => (info.names?.some((n) => n.endsWith('.css')) ? 'draft.css' : 'draft-asset-[name][extname]'),
            },
        },
    },
});
