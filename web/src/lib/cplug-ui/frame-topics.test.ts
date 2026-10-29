import { describe, expect, test } from 'vitest';
import { createFrameTopics, parseTopic, type TopicPage, type TopicPush } from './frame-topics';

function rig() {
    let listener: ((topics: string[]) => void) | null = null;
    let seen: (() => void) | null = null;
    const state = { hidden: false, live: true };
    const push: TopicPush = { onChange: (fn) => { listener = fn; return () => undefined; }, isLive: () => state.live };
    const page: TopicPage = { hidden: () => state.hidden, onVisibilityChange: (fn) => { seen = fn; return () => undefined; } };
    const topics = createFrameTopics(push, page);
    return {
        topics, state,
        push: (...names: string[]) => listener?.(names),
        show: () => { state.hidden = false; seen?.(); },
    };
}

describe('parseTopic', () => {
    test('takes the three shapes the server names and nothing looser', () => {
        expect(parseTopic('cplug_topic:u1:runs')).toEqual({ install: 'u1', name: 'runs', key: null });
        expect(parseTopic('cplug_topic:u1:runs:r-1')).toEqual({ install: 'u1', name: 'runs', key: 'r-1' });
        for (const bad of ['cplug_ui:u1', 'cplug_topic:u1', 'cplug_topic:u1:Runs', 'cplug_topic:u1:runs:Bad Key', 'cplug_topic:u1:runs:a:b', 'cplug_topic::runs', 'layouts']) {
            expect(parseTopic(bad), bad).toBeNull();
        }
    });
});

describe('frame topics', () => {
    test('a push for install X reaches the mounted frame of X and no frame of another install', () => {
        const r = rig();
        const x: unknown[] = [];
        const y: unknown[] = [];
        r.topics.register('x', (name, key) => x.push([name, key]), () => true);
        r.topics.register('y', (name, key) => y.push([name, key]), () => true);
        r.push('cplug_topic:x:runs:r1', 'cplug_ui:x', 'cplug_topic:zzz:runs');
        expect(x).toEqual([['runs', 'r1']]);
        expect(y).toEqual([]);
    });

    test('a hidden page holds the push and delivers one per name when it is shown', () => {
        const r = rig();
        const got: unknown[] = [];
        r.topics.register('x', (name, key) => got.push([name, key]), () => true);
        r.state.hidden = true;
        r.push('cplug_topic:x:runs:r1');
        r.push('cplug_topic:x:runs:r2', 'cplug_topic:x:feed');
        expect(got).toEqual([]);
        r.show();
        expect(got).toEqual([['runs', null], ['feed', null]]);
        r.show();
        expect(got).toHaveLength(2);
    });

    test('the same key twice stays that key; a different key under a held name widens to the name', () => {
        const r = rig();
        const got: unknown[] = [];
        r.topics.register('x', (name, key) => got.push([name, key]), () => true);
        r.state.hidden = true;
        r.push('cplug_topic:x:runs:r1', 'cplug_topic:x:runs:r1');
        r.show();
        expect(got).toEqual([['runs', 'r1']]);
    });

    test('a frame that is not visible holds until refresh, and a released frame hears nothing', () => {
        const r = rig();
        const got: string[] = [];
        let visible = false;
        const handle = r.topics.register('x', (name) => got.push(name), () => visible);
        r.push('cplug_topic:x:runs');
        expect(got).toEqual([]);
        visible = true;
        handle.refresh();
        expect(got).toEqual(['runs']);
        handle.release();
        r.push('cplug_topic:x:runs');
        expect(got).toEqual(['runs']);
    });

    test('the topic feature is offered only while the server advertises the family', () => {
        const r = rig();
        expect(r.topics.live()).toBe(true);
        r.state.live = false;
        expect(r.topics.live()).toBe(false);
    });
});
