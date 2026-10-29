/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import RankPanel, { type RankRow } from './RankPanel.svelte';

const mounted: Array<Record<string, unknown>> = [];

function draw(rows: RankRow[]): HTMLElement {
    const host = document.createElement('div');
    document.body.appendChild(host);
    mounted.push(mount(RankPanel, { target: host, props: { label: 'panel', rows, notMeasured: 'not measured' } as never }));
    flushSync();
    return host;
}

afterEach(() => {
    while (mounted.length) unmount(mounted.pop() as never);
    document.body.innerHTML = '';
});

describe('RankPanel tile', () => {
    test('mark, icon, or the first letter: never an empty tile', () => {
        const host = draw([
            { id: 'a', name: 'alpha', iconSvg: '<svg aria-hidden="true"></svg>', metric: null },
            { id: 'b', name: 'bravo', icon: 'terminal', metric: null },
            { id: 'c', name: 'charlie', metric: null },
        ]);
        const tiles = [...host.querySelectorAll('.oc-rank__tile')];
        expect(tiles.length).toBe(3);
        expect(tiles[0]!.querySelector('svg')).not.toBeNull();
        expect(tiles[1]!.querySelector('svg')).not.toBeNull();
        expect(tiles[2]!.textContent?.trim()).toBe('C');
    });
});
