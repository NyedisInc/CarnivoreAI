/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const listBlueprints = vi.hoisted(() => vi.fn());
vi.mock('./api', async (actual) => ({
    ...(await actual<typeof import('./api')>()),
    listBlueprints,
}));

const openBlueprintsScreen = vi.hoisted(() => vi.fn());
vi.mock('./screen-host', () => ({ openBlueprintsScreen }));

import { openBlueprintPicker } from './blueprint-picker';

afterEach(() => {
    document.body.innerHTML = '';
    vi.clearAllMocks();
});

function anchorEl(): HTMLElement {
    const el = document.createElement('button');
    document.body.append(el);
    return el;
}

describe('openBlueprintPicker', () => {
    test('lists every saved blueprint next to the anchor, each launching directly', async () => {
        listBlueprints.mockResolvedValueOnce({
            status: 'ok',
            detail: null,
            blueprints: [
                { blueprint_uuid: 'b1', name: 'review team', spec: { version: 1, name: 'review team', shape_template: null, sessions: [] }, created_at: '', updated_at: '' },
            ],
        });
        await openBlueprintPicker(anchorEl());
        const labels = Array.from(document.querySelectorAll('.acm-item .acm-label')).map((el) => el.textContent);
        expect(labels).toContain('review team');
        expect(labels).toContain('View all');
    });

    test('an unavailable store falls back to the general screen instead of an empty popover', async () => {
        listBlueprints.mockResolvedValueOnce({ status: 'unavailable', detail: 'store unreadable', blueprints: [] });
        await openBlueprintPicker(anchorEl());
        expect(openBlueprintsScreen).toHaveBeenCalledTimes(1);
        expect(document.querySelector('.acm-menu')).toBeNull();
    });

    test('a read failure also falls back to the general screen', async () => {
        listBlueprints.mockRejectedValueOnce(new Error('network'));
        await openBlueprintPicker(anchorEl());
        expect(openBlueprintsScreen).toHaveBeenCalledTimes(1);
    });

    test('no saved blueprints draws one blocked line, not an empty popover', async () => {
        listBlueprints.mockResolvedValueOnce({ status: 'ok', detail: null, blueprints: [] });
        await openBlueprintPicker(anchorEl());
        const blocked = document.querySelector('.acm-item[aria-disabled="true"] .acm-label');
        expect(blocked?.textContent).toBe('no blueprints yet');
    });
});
