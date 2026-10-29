/* the widget harness page */
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { popupFocusLast } from './vite.widget-harness.shared';

const root = fileURLToPath(new URL('./src/widget-harness', import.meta.url));

const outDir = fileURLToPath(new URL('../client/dist/widget-lab', import.meta.url));

export default defineConfig({
    root,
    base: '/static/dist/widget-lab/',
    plugins: [svelte(), tailwindcss(), popupFocusLast()],
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
                entryFileNames: 'widget-lab.js',
                chunkFileNames: 'widget-lab-chunk-[name].js',
                assetFileNames: (info) => (info.names?.some((n) => n.endsWith('.css')) ? 'widget-lab.css' : 'widget-lab-asset-[name][extname]'),
            },
        },
    },
});
