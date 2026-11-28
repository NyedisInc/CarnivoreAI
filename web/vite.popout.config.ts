import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { dedupeI18nPlugin } from './vite.i18n-shared';
import { tomlPlugin } from './vite.toml-plugin';

const entry = fileURLToPath(new URL('./src/popout/main.ts', import.meta.url));

const outDir = fileURLToPath(new URL('../client/dist', import.meta.url));

export default defineConfig({
    base: '/static/dist/',
    plugins: [tomlPlugin(), dedupeI18nPlugin(), svelte(), tailwindcss()],
    build: {
        outDir,
        emptyOutDir: false,
        minify: 'oxc',
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
        modulePreload: { polyfill: false },
        rollupOptions: {
            input: entry,
            output: {
                entryFileNames: 'popout.js',
                chunkFileNames: 'popout-chunk-[name].js',
                assetFileNames: (info) =>
                    info.names?.some((n) => n.endsWith('.css'))
                        ? 'popout.css'
                        : 'popout-asset-[name][extname]',
            },
        },
    },
});
