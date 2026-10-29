/** @vitest-environment jsdom */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', () => ({
    auth: { state: 'signed-in' },
    initAuth: async () => {},
    ApiError: class ApiError extends Error {},
    authFetch: async () => null,
}));

import PipelineStatusPanel from './PipelineStatusPanel.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher, PipelineStatus } from './api';
import { SETTINGS, settingsIn } from '../settings-page/settings-registry';

setLocale('en');

const WEB_SRC = resolve(__dirname, '../..');
const CLIENT_JS = resolve(__dirname, '../../../../client/js');

function sources(dir: string): string[] {
    const out: string[] = [];
    for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) out.push(...sources(path));
        else if (/\.(ts|svelte|js)$/.test(name)) out.push(path);
    }
    return out;
}

const apps: ReturnType<typeof mount>[] = [];
beforeEach(() => { document.body.innerHTML = ''; });
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

const status = (): PipelineStatus => ({
    state: 'behind', lag: { files: 4, seconds: 30 }, last_delivery_at: null, stalled_since: null, rebuilding: [], recent: [], running: [], queue: { items: [], total: 0 },
    plugins: {
        stats: { lag: { files: 4, seconds: 30 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: null, runs: 0 },
        deepsearch: { lag: { files: 0, seconds: 0 }, failures: 0, last_error: null, rebuilding: false, last_delivery_at: null, runs: 0 },
    },
}) as PipelineStatus;

describe('Settings, pipeline', () => {
    test('is one status panel and the deep search scope control, nothing else', () => {
        const items = settingsIn('log_processor');
        expect(items.length, 'the registry names the pipeline section\'s controls').toBeGreaterThan(0);
        expect(items.map((item) => item.control.kind)).toEqual(['pipeline-status', 'deepsearch-scope']);
        expect(SETTINGS.some((item) => /grant|approv|data_?view|start_?point|slow|backfill/i.test(item.id))).toBe(false);
    });

    test('the panel draws the line and one rebuild button per plugin, no governance control', async () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        const fetcher = (async () => status()) as unknown as Fetcher;
        apps.push(mount(PipelineStatusPanel, { target, props: { fetcher } }));
        await settle();

        expect(target.querySelector('[data-ps="line"]'), 'the panel found its status line').not.toBeNull();
        const rows = target.querySelectorAll('[data-ps-plugin]');
        expect(rows.length, 'the panel found its plugin rows').toBe(2);
        expect(target.querySelectorAll('input, select, textarea, [role="switch"], [role="checkbox"]').length).toBe(0);
        const buttons = [...target.querySelectorAll('button')];
        expect(buttons.length).toBe(rows.length);
        expect(buttons.every((button) => button.getAttribute('data-ps') === 'rebuild')).toBe(true);
        const words = (target.textContent ?? '').toLowerCase();
        for (const banned of ['grant', 'approve', 'data view', 'start point', 'slow lane', 'backfill', 'pause', 'permission']) {
            expect(words, `the panel never says "${banned}"`).not.toContain(banned);
        }
    });
});

describe('the sources', () => {
    const files = [...sources(WEB_SRC), ...sources(CLIENT_JS)].filter((path) => !path.endsWith('no-approval-screens.test.ts'));

    test('the scan looked at the real tree', () => {
        expect(files.length, 'a scan of nothing is not a pass').toBeGreaterThan(500);
        expect(files.some((path) => path.endsWith('PipelineStatusPanel.svelte'))).toBe(true);
    });

    test('nothing calls the governance routes or names a deleted screen', () => {
        const banned = [/['"`]\/log-processor\//, /CplugRow\.svelte/, /CplugsPanel\.svelte/, /SummaryAiPanel/, /\/log_processor\/addons/];
        const hits = files.flatMap((path) => {
            const text = readFileSync(path, 'utf8');
            return banned.filter((re) => re.test(text)).map((re) => `${path.slice(WEB_SRC.length)} ${re}`);
        });
        expect(hits).toEqual([]);
    });

    test('no catalog string words a pipeline data view, a start point or a slow lane', () => {
        const catalog = readFileSync(join(CLIENT_JS, 'i18n/catalog.en.js'), 'utf8');
        expect(catalog.split('\n').length, 'the catalog was read').toBeGreaterThan(5000);
        expect(catalog.match(/'(?:data view|start point|slow lane)[^']*'|:\s*'[^']*\b(?:data view|start point|slow lane)\b/gi) ?? []).toEqual([]);
    });
});

describe('the Plugins page keeps its own permission sheet', () => {
    test('PermissionSheet is the plugin platform\'s and is still there', () => {
        const sheet = readFileSync(join(WEB_SRC, 'lib/plugins-page/PermissionSheet.svelte'), 'utf8');
        expect(sheet).toContain('docs/cplug-platform.md');
    });
});
