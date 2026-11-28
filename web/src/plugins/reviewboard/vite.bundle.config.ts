import { defineConfig, type Plugin } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { tomlPlugin } from '../../../vite.toml-plugin';

const PUBLIC_KEY_PREFIX = 'cplug.reviewboard.public.';

function publicStringsOnly(): Plugin {
    return {
        name: 'reviewboard-public-strings-only',
        enforce: 'pre',
        transform(code, id) {
            if (!/\/reviewboard\/catalog\.en\.js$/.test(id.split('?')[0]!)) return null;
            const slice = new Function(`return (${code.replace(/^[\s\S]*?export default/, '').replace(/;\s*$/, '')});`)() as Record<string, unknown>;
            const kept = Object.fromEntries(Object.entries(slice).filter(([key]) => key.startsWith(PUBLIC_KEY_PREFIX)));
            return { code: `export default ${JSON.stringify(kept)};`, map: null };
        },
    };
}

const entry = fileURLToPath(new URL('./public/visitor-page/main.ts', import.meta.url));

const outDir = fileURLToPath(new URL('../../../../client/dist', import.meta.url));

export default defineConfig({
    plugins: [tomlPlugin(), publicStringsOnly(), svelte()],
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
                entryFileNames: 'reviewboard-public.js',
                codeSplitting: false,
                assetFileNames: (info) =>
                    info.names?.some((n) => n.endsWith('.css')) ? 'reviewboard-public.css' : 'reviewboard-public-asset-[name][extname]',
            },
        },
    },
});
