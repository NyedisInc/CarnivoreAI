import { build, createServer } from 'vite';
import { render } from 'svelte/server';
import { copyFile, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const webDir = fileURLToPath(new URL('../..', import.meta.url));
const configFile = join(webDir, 'vite.public-site.config.ts');
const defaultOutput = resolve(webDir, '../hosted/site');
const headMarker = '<!-- PUBLIC_SITE_HEAD -->';
const contentMarker = '<!-- PUBLIC_SITE_CONTENT -->';

function outputDirectory(args) {
    if (args.length === 0) return defaultOutput;
    if (args.length === 2 && args[0] === '--output-dir' && args[1]) {
        return resolve(args[1]);
    }
    throw new Error('Usage: npm run site:build -- [--output-dir <directory>]');
}

function replaceOne(html, marker, replacement) {
    const first = html.indexOf(marker);
    if (first < 0 || html.indexOf(marker, first + marker.length) >= 0) {
        throw new Error(`Expected exactly one ${marker} in public site document`);
    }
    return html.replace(marker, replacement);
}

async function publish(staged, destination) {
    const assets = join(staged, 'assets');
    const names = await readdir(assets);
    await mkdir(join(destination, 'assets'), { recursive: true });
    for (const name of names) {
        await copyFile(join(assets, name), join(destination, 'assets', name));
    }
    await copyFile(join(staged, 'index.html'), join(destination, 'index.html'));
}

async function main() {
    const destination = outputDirectory(process.argv.slice(2));
    const staged = await mkdtemp(join(tmpdir(), 'carnivore-site-'));
    process.env.CARNIVORE_SITE_BUILD_DIR = staged;
    try {
        await build({ configFile, logLevel: 'warn' });

        const server = await createServer({
            configFile,
            logLevel: 'error',
            server: { middlewareMode: true, hmr: false },
            appType: 'custom',
        });
        let rendered;
        try {
            const { default: Page } = await server.ssrLoadModule('/Page.svelte');
            rendered = render(Page);
        } finally {
            await server.close();
        }

        const document = await readFile(join(staged, 'document.html'), 'utf8');
        const withHead = replaceOne(document, headMarker, rendered.head);
        const html = replaceOne(withHead, contentMarker, rendered.body);
        if (!html.includes('./assets/public-site.js') ||
            !html.includes('./assets/public-site.css')) {
            throw new Error('Public site document does not reference fixed local JS and CSS assets');
        }
        await readFile(join(staged, 'assets/public-site.js'));
        await readFile(join(staged, 'assets/public-site.css'));
        await writeFile(join(staged, 'index.html'), html);
        await publish(staged, destination);
    } finally {
        await rm(staged, { recursive: true, force: true });
    }
}

await main();
