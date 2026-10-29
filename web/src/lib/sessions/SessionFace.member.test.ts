/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const lights: Record<string, unknown>[] = [];

vi.mock('../StatusLed.svelte', () => ({
    default: (_anchor: unknown, props: Record<string, unknown>) => { lights.push({ status: props.status }); },
}));

import SessionFace from './SessionFace.svelte';
import { registerSwarmFace, swarmFace, unregisterSwarmFace } from '../../cplugs/sdk/swarm-face.svelte';
import type { Component } from 'svelte';
import type { SwarmFaceProps } from '../../cplugs/sdk/swarm-face.svelte';

const Character = ((anchor: Comment) => {
    const mark = document.createElement('i');
    mark.dataset.character = 'yes';
    anchor.parentNode?.insertBefore(mark, anchor);
}) as unknown as Component<SwarmFaceProps>;

const MEMBER = { agentId: 7, rank: 'feature', seed: 7 };
const ROW = { agent_family: 'claude', activity_status: 'idle' };

let app: Record<string, unknown> | null = null;
afterEach(() => {
    if (app) unmount(app);
    app = null;
    lights.length = 0;
    unregisterSwarmFace();
    document.body.innerHTML = '';
});

function memberFace(): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    app = mount(SessionFace as never, { target, props: { row: ROW, member: MEMBER } });
    flushSync();
    return target;
}

describe('a Swarm member row', () => {
    test('with the plugin\'s character registered, draws the character and not the light', () => {
        registerSwarmFace(Character);
        const host = memberFace();
        expect(host.querySelector('[data-character]')).not.toBeNull();
        expect(lights).toEqual([]);
    });

    test('with no character registered, draws the plain status light and no member slot', () => {
        const host = memberFace();
        expect(lights).toEqual([{ status: 'idle' }]);
        expect(host.querySelector('.swarm-row-face')).toBeNull();
    });

    test('after the plugin stops (unregister), the light comes back', () => {
        registerSwarmFace(Character);
        unregisterSwarmFace();
        expect(swarmFace.component).toBeNull();
        memberFace();
        expect(lights).toEqual([{ status: 'idle' }]);
    });
});
