import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('./src/public-site', import.meta.url));
const document = fileURLToPath(new URL('./src/public-site/document.html', import.meta.url));
const svelteConfig = fileURLToPath(new URL('./svelte.config.js', import.meta.url));
const outDir = process.env.CARNIVORE_SITE_BUILD_DIR;

if (!outDir) {
    throw new Error('Run the public site build through npm run site:build');
}

export default defineConfig({
    root,
    base: './',
    publicDir: false,
    plugins: [svelte({ configFile: svelteConfig }), tailwindcss()],
    build: {
        outDir,
        emptyOutDir: true,
        modulePreload: false,
        minify: 'oxc',
        target: 'es2022',
        sourcemap: false,
        cssCodeSplit: false,
        rollupOptions: {
            input: document,
            output: {
                entryFileNames: 'assets/public-site.js',
                chunkFileNames: 'assets/public-site-chunk-[name].js',
                assetFileNames: (info) =>
                    info.names?.some((name) => name.endsWith('.css'))
                        ? 'assets/public-site.css'
                        : 'assets/public-site-asset-[name][extname]',
            },
        },
    },
});
