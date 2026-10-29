/** @vitest-environment jsdom */
import { mount, unmount, tick } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import InstallReportPrivacyPanel from './InstallReportPrivacyPanel.svelte';
import type { Fetcher } from './disclosure-api';

let handle: ReturnType<typeof mount> | null = null;
const settle = async () => { await tick(); await new Promise((r) => setTimeout(r, 0)); await tick(); };
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; });

async function draw(fetcher: Fetcher): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    handle = mount(InstallReportPrivacyPanel, { target, props: { t: (key: string) => key, fetcher } });
    await settle();
    return target;
}

describe('the install report privacy panel', () => {
    it('lists every field the route names, in both groups, with a sentence key each', async () => {
        const body = { report: ['item_id', 'version', 'account_id'], guest: ['public_key', 'install_id'] };
        const target = await draw((async () => body) as unknown as Fetcher);
        const report = [...target.querySelectorAll('[data-install-report-fields="report"] li')].map((li) => li.textContent);
        expect(report).toHaveLength(3);
        expect(report[0]).toContain('item_id');
        expect(report[0]).toContain('privacy.install_report.field.item_id');
        expect(target.querySelectorAll('[data-install-report-fields="guest"] li')).toHaveLength(2);
        expect(target.textContent).toContain('privacy.install_report.panel.no_switch');
        expect(target.querySelector('input[type="checkbox"], [role="switch"]')).toBeNull();
    });

    it('shows a problem sentence, not an empty list, when the route fails', async () => {
        const target = await draw((async () => { throw new Error('boom'); }) as unknown as Fetcher);
        expect(target.querySelector('[role="alert"]')?.textContent).toBe('boom');
        expect(target.querySelectorAll('li')).toHaveLength(0);
    });
});
