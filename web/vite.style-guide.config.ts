import { defineConfig, type Plugin } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

const entry = fileURLToPath(new URL('./src/style-guide/main.ts', import.meta.url));

const outDir = fileURLToPath(new URL('../client/dist', import.meta.url));

function dropCss(): Plugin {
    return {
        name: 'style-guide-drop-css',
        enforce: 'post',
        generateBundle: {
            order: 'post',
            handler(_options, bundle) {
                for (const name of Object.keys(bundle)) {
                    if (name.endsWith('.css')) delete bundle[name];
                }
            },
        },
    };
}

export default defineConfig({
    plugins: [svelte(), dropCss()],
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
                entryFileNames: 'style-guide.js',
                chunkFileNames: 'style-guide-chunk-[name].js',
                assetFileNames: 'style-guide-asset-[name][extname]',
            },
        },
    },
});
