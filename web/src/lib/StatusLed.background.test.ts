import { describe, expect, test } from 'vitest';

import { ledStateFor } from './led';
import { backgroundLabel, ledHtmlForStatus, statusTitle } from './status-dot';
import { legacy } from './led-legacy-fixture';
import { countAgents } from './drawer/agent-counts';
import { statusHue, statusLabel } from '../opscenter/api/sessions.svelte';

describe('the gray spinner', () => {
    test('the pair paints a still gray ring around the background shape, in both trees', () => {
        const signals = { activity_hint: 'background' };
        expect(ledStateFor({ activity_status: 'working_subagent', ...signals })).toEqual({ inner: 'background', outer: 'steady' });
        expect(legacy().ledStateFor({ activity_status: 'working_subagent', ...signals })).toEqual({ inner: 'background', outer: 'steady' });
        const html = ledHtmlForStatus('working_subagent', signals);
        expect(html).toContain('data-inner="background"');
        expect(html).toContain(backgroundLabel());
        expect(legacy().dotHtml('working_subagent', signals)).toBe(html);
    });

    test('it can go red: no hint, or another status, keeps the green working arc', () => {
        expect(ledStateFor({ activity_status: 'working_subagent' })).toEqual({ inner: 'working', outer: 'active' });
        expect(ledStateFor({ activity_status: 'working', activity_hint: 'background' })).toEqual({ inner: 'working', outer: 'active' });
        expect(ledStateFor({ activity_status: 'idle', activity_hint: 'background' }).inner).toBe('idle');
        expect(ledHtmlForStatus('working_subagent')).toContain('data-inner="working"');
    });

    test('it reads as different from idle, unknown and working, with its own label', () => {
        const inners = ['working', 'idle', 'unknown'].map((s) => ledStateFor({ activity_status: s }).inner);
        const bg = ledStateFor({ activity_status: 'working_subagent', activity_hint: 'background' });
        expect(inners).not.toContain(bg.inner);
        const label = statusTitle('working_subagent', null, 'background', false);
        expect(label).toBe(backgroundLabel());
        expect(label).not.toBe(statusTitle('working_subagent', null, null, false));
    });

    test('a cell label and hue follow, and the drawer working count leaves it out', () => {
        expect(statusHue('working_subagent', null, null, null, null, 'background')).toBe('grey');
        expect(statusHue('working_subagent')).toBe('green');
        expect(statusLabel('working_subagent', null, null, null, 'background')).toBe(backgroundLabel());
        const rows = [
            { name: 'a', status: 'working_subagent', activity_hint: 'background' },
            { name: 'b', status: 'working_subagent' },
            { name: 'c', status: 'working' },
        ];
        const counts = countAgents(rows as never);
        expect(counts.active).toBe(3);
        expect(counts.working).toBe(2);
    });
});
