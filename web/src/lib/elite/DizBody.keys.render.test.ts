/** @vitest-environment jsdom */
import { mount, unmount } from 'svelte';
import { afterEach, describe, expect, test } from 'vitest';

import type { CommunityHost } from '../community/community';
import type { Translate } from '../sessions/types';
import DizBody from './DizBody.svelte';
import type { DizModel } from './diz-model';

const t: Translate = (key) => key;
const host = { comments: () => Promise.resolve({ items: [], more: false }) } as unknown as CommunityHost;

function repeatingModel(): DizModel {
    return {
        id: 'alex/dusk', name: 'dusk', byLine: 'alex/dusk', kind: 'theme', kindTag: 'theme', verdict: 'clean', verdictTag: 'clean',
        stateKind: 'avail', stateText: 'available', rating: null,
        actions: { addLabel: 'add', addOffline: false, tryable: false, tryLabel: 'try' },
        dl: null, brief: 'b', link: 'l', versionsHead: 'v', works: 'w',
        versions: [{ line: '1.0  12 KB  2026-10-01', mark: '' }, { line: '1.0  12 KB  2026-10-01', mark: '' }],
        swatches: ['#112233', '#112233', '#ffffff'],
        trust: { on: 1, off: 1 }, trustWord: 'ok', trustWhy: 'why', grade: { on: 1, off: 1 }, gradeWord: 'A', live: '',
    } as unknown as DizModel;
}

let mounted: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (mounted) void unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

describe('DizBody repeated list values', () => {
    test('renders every swatch and every version row even when values repeat', () => {
        mounted = mount(DizBody, {
            target: document.body,
            props: { model: repeatingModel(), t, host, say: () => {}, onAdd: () => {}, onTry: () => {}, offline: false },
        });
        expect(document.querySelectorAll('.sw')).toHaveLength(3);
        expect(document.querySelectorAll('.dz-r:not(.dz-h)')).toHaveLength(2);
    });
});
