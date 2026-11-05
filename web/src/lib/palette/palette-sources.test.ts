import { describe, expect, it, vi } from 'vitest';

const opened = vi.hoisted(() => ({ dashboard: vi.fn(), browser: vi.fn(() => true), guide: vi.fn(() => true) }));
vi.mock('../dashboards/dashboard-actions.svelte', () => ({ showDashboard: opened.dashboard }));
vi.mock('../browser/screen-host', () => ({ openBrowser: opened.browser }));
vi.mock('../user-guide/guide-nav', () => ({ followGuideTarget: opened.guide }));

import { browserItems, dashboardItems, fileItems, helpItems } from './palette-sources';
import type { BrowserInfo } from '../browser/api.svelte';
import type { PageInfo } from '../browser/page-frame';
import type { OpenFileInfo } from '../open-files/api.svelte';
import type { GuideSection } from '../user-guide/guide-content';

const B = 'a'.repeat(16);
const P = 'b'.repeat(16);
const F = 'c'.repeat(16);

describe('palette sources', () => {
    it('dashboards, browser pages, open files and help are rows that open their own target', () => {
        const dash = dashboardItems([{ id: 'ops', name: 'ops wall' }]);
        expect(dash.map((i) => [i.kind, i.title])).toEqual([['dashboard', 'ops wall']]);
        dash[0]!.run({ popout: false });
        expect(opened.dashboard).toHaveBeenCalledWith('ops');

        const web = browserItems(
            [{ id: B, label: 'docs site', url: 'https://example.com' } as BrowserInfo],
            [{ id: P, key: 'k', title: 'artifact' } as PageInfo],
        );
        expect(web.map((i) => [i.kind, i.title])).toEqual([['browser', 'docs site'], ['browser', 'artifact']]);
        web[1]!.run({ popout: false });
        expect(opened.browser).toHaveBeenLastCalledWith(P);

        const files = fileItems([{ id: F, title: 'main.py', path: 'src/main.py' } as OpenFileInfo]);
        expect(files[0]).toMatchObject({ kind: 'file', title: 'main.py' });
        expect(files[0]!.subtitle).toContain('src/main.py');
        files[0]!.run({ popout: false });
        expect(opened.browser).toHaveBeenLastCalledWith(F);

        const help = helpItems([{ id: 'sidebar', title: 'the sidebar' } as GuideSection]);
        expect(help.map((i) => [i.kind, i.title])).toEqual([['help', 'the sidebar']]);
        help[0]!.run({ popout: false });
        expect(opened.guide).toHaveBeenCalledWith('#docs/sidebar');
    });
});
