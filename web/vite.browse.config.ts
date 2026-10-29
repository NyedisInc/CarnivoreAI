import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';

const svelteConfig = fileURLToPath(new URL('./svelte.config.js', import.meta.url));
const root = fileURLToPath(new URL('./src/browse', import.meta.url));
const outDir = fileURLToPath(new URL('../hosted/catalog_index/site/browse', import.meta.url));
const cardMediaStatic = fileURLToPath(new URL('./src/browse/card-media-static.ts', import.meta.url));
const authStatic = fileURLToPath(new URL('./src/browse/auth-static.ts', import.meta.url));
const fonts = fileURLToPath(new URL('../client/fonts/', import.meta.url));

export default defineConfig({
    root,
    base: './',
    plugins: [svelte({ configFile: svelteConfig }), tailwindcss()],
    resolve: {
        alias: [
            { find: /^\/static\/fonts\//, replacement: fonts },
            { find: /^(?:\.\.?\/)+(?:opscenter\/)?(?:api\/)?auth\.svelte$|^\.\/auth\.svelte$/, replacement: authStatic },
            { find: /^(?:\.\.?\/)+(?:lib\/)?(?:catalog\/)?card-media$|^\.\/card-media$/, replacement: cardMediaStatic },
        ],
    },
    build: {
        outDir,
        emptyOutDir: true,
        modulePreload: false,
        minify: 'oxc',
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
        assetsInlineLimit: 0,
        rollupOptions: {
            output: {
                entryFileNames: 'browse.js',
                chunkFileNames: 'chunk-[name].js',
                assetFileNames: (info) =>
                    info.names?.some((n) => n.endsWith('.css')) ? 'browse.css' : 'asset-[name][extname]',
            },
        },
    },
});
