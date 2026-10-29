/* <script */
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

const svelteConfig = fileURLToPath(new URL('./svelte.config.js', import.meta.url));

const root = fileURLToPath(new URL('./src/admin', import.meta.url));

const outDir = fileURLToPath(
    new URL('../hosted/catalog/admin/dist', import.meta.url),
);

export default defineConfig({
    root,
    base: './',
    plugins: [svelte({ configFile: svelteConfig })],
    build: {
        outDir,
        emptyOutDir: true,
        modulePreload: false,
        minify: 'oxc',
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
        rollupOptions: {
            output: {
                entryFileNames: 'admin.js',
                chunkFileNames: 'chunk-[name].js',
                assetFileNames: (info) =>
                    info.names?.some((n) => n.endsWith('.css'))
                        ? 'admin.css'
                        : 'asset-[name][extname]',
            },
        },
    },
});
