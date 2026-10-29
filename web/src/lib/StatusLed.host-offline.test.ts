import { describe, expect, test } from 'vitest';

import { hostOffline, ledStateFor } from './led';
import { ledHtmlForStatus } from './status-dot';
import { legacy } from './led-legacy-fixture';

const DOWN = { host_key: 'peer-ab12', host_label: 'studio', host_state: 'disconnected' };
const UP = { ...DOWN, host_state: 'up' };

describe('a row of an unreachable paired Mac', () => {
    test('hostOffline names the Mac only for a remote row whose link is not up, in both trees', () => {
        const api = legacy();
        for (const [row, want] of [
            [DOWN, 'studio'],
            [{ ...DOWN, host_state: 'connecting' }, 'studio'],
            [{ ...DOWN, host_label: undefined }, 'peer-ab12'],
            [UP, null],
            [{ host_key: 'local', host_label: 'this machine', host_state: 'disconnected' }, null],
            [{}, null],
            [null, null],
        ] as const) {
            expect(hostOffline(row)).toBe(want);
            expect(api.hostOffline(row)).toBe(want);
        }
    });

    test('the light is the red disconnected one whatever the last status, and clears on reconnect', () => {
        for (const status of ['working', 'idle', 'question', 'unknown']) {
            expect(ledStateFor({ activity_status: status, host_offline: hostOffline(DOWN) })).toEqual({
                inner: 'disconnected',
                outer: 'off',
            });
            expect(ledStateFor({ activity_status: status, host_offline: hostOffline(UP) })).not.toEqual({
                inner: 'disconnected',
                outer: 'off',
            });
        }
    });

    test('the tooltip names the Mac, identically in both trees, and an asleep row keeps its moon', () => {
        const api = legacy();
        const signals = { host_offline: 'studio' };
        const mine = ledHtmlForStatus('working', signals);
        expect(mine).toContain('title="studio offline"');
        expect(mine).toContain('data-inner="disconnected"');
        expect(api.dotHtml('working', signals)).toBe(mine);
        const asleep = ledHtmlForStatus('asleep', signals);
        expect(asleep).toContain('data-inner="asleep"');
        expect(api.dotHtml('asleep', signals)).toBe(asleep);
    });
});
