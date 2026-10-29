import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { popupFocusLast } from './vite.widget-harness.shared';

const root = fileURLToPath(new URL('./src/widget-harness', import.meta.url));

const outDir = fileURLToPath(new URL('../client/widget-harness-build', import.meta.url));

export default defineConfig({
    root,
    base: '/static/widget-harness-build/',
    plugins: [svelte(), tailwindcss(), popupFocusLast()],
    build: {
        outDir,
        emptyOutDir: true,
        minify: false,
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
    },
});
