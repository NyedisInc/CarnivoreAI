import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { dedupeI18nPlugin } from './vite.i18n-shared';
import { tomlPlugin } from './vite.toml-plugin';

const entry = fileURLToPath(new URL('./src/lib/notify-card/corner.ts', import.meta.url));

const outDir = fileURLToPath(new URL('../client/dist', import.meta.url));

export default defineConfig({
    plugins: [tomlPlugin(), dedupeI18nPlugin({ dropPluginSlices: true }), svelte()],
    build: {
        outDir,
        emptyOutDir: false,
        minify: 'oxc',
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
        rollupOptions: {
            input: entry,
            output: {
                entryFileNames: 'notify-corner.js',
                chunkFileNames: 'notify-corner-chunk-[name].js',
                assetFileNames: (info) =>
                    info.names?.some((n) => n.endsWith('.css')) ? 'notify-corner.css' : 'notify-corner-asset-[name][extname]',
            },
        },
    },
});
