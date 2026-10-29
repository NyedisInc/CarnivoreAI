/* and the three */
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

const entry = fileURLToPath(new URL('./src/pair/main.ts', import.meta.url));

const outDir = fileURLToPath(new URL('../client/dist', import.meta.url));

export default defineConfig({
    plugins: [svelte()],
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
                entryFileNames: 'pair.js',
                chunkFileNames: 'pair-chunk-[name].js',
                assetFileNames: (info) =>
                    info.names?.some((n) => n.endsWith('.css')) ? 'pair.css' : 'pair-asset-[name][extname]',
            },
        },
    },
});
