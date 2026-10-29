import { resourcePush } from '../resource-push/boot';

export const TOPIC_FAMILY = 'cplug_topic';
const NAME = /^[a-z][a-z0-9_]{0,23}$/;
const KEY = /^[a-z0-9_-]{1,40}$/;

export interface TopicPush {
    onChange(fn: (topics: string[]) => void): () => void;
    isLive(topic: string): boolean;
}

export interface TopicPage {
    hidden(): boolean;
    onVisibilityChange(fn: () => void): () => void;
}

export interface FrameTopicHandle {
    refresh(): void;
    release(): void;
}

export function parseTopic(topic: string): { install: string; name: string; key: string | null } | null {
    const parts = topic.split(':');
    if (parts[0] !== TOPIC_FAMILY || parts.length < 3 || parts.length > 4) return null;
    const [, install, name, key] = parts;
    if (!install || !name || !NAME.test(name) || (key !== undefined && !KEY.test(key))) return null;
    return { install, name, key: key ?? null };
}

export function createFrameTopics(push: TopicPush, page: TopicPage) {
    interface Sub {
        readonly install: string;
        readonly deliver: (name: string, key: string | null) => void;
        readonly visible: () => boolean;
        readonly held: Map<string, string | null>;
    }
    const subs = new Set<Sub>();

    const canSee = (sub: Sub): boolean => !page.hidden() && sub.visible();
    const flush = (sub: Sub): void => {
        if (!canSee(sub) || sub.held.size === 0) return;
        const held = [...sub.held];
        sub.held.clear();
        for (const [name, key] of held) sub.deliver(name, key);
    };

    push.onChange((topics) => {
        for (const topic of topics) {
            const parsed = parseTopic(topic);
            if (!parsed) continue;
            for (const sub of subs) {
                if (sub.install !== parsed.install) continue;
                sub.held.set(parsed.name, sub.held.has(parsed.name) && sub.held.get(parsed.name) !== parsed.key ? null : parsed.key);
                flush(sub);
            }
        }
    });
    page.onVisibilityChange(() => { for (const sub of subs) flush(sub); });

    return {
        live: (): boolean => push.isLive(TOPIC_FAMILY),
        register(install: string, deliver: Sub['deliver'], visible: () => boolean): FrameTopicHandle {
            const sub: Sub = { install, deliver, visible, held: new Map() };
            subs.add(sub);
            return { refresh: () => flush(sub), release: () => { subs.delete(sub); } };
        },
    };
}

let shared: ReturnType<typeof createFrameTopics> | null = null;

export function frameTopics(): ReturnType<typeof createFrameTopics> {
    shared ??= createFrameTopics(resourcePush(), {
        hidden: () => typeof document !== 'undefined' && document.hidden,
        onVisibilityChange: (fn) => {
            document.addEventListener('visibilitychange', fn);
            return () => document.removeEventListener('visibilitychange', fn);
        },
    });
    return shared;
}
