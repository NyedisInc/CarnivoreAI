import { describe, expect, it } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { vi } from 'vitest';
import { attach, messaging, problemText, refresh, refusalReason } from './store.svelte';

vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {} }) }));

const t = (key: string) => (key === 'messaging.ui.error.provider_unreachable' ? 'the provider did not answer.' : key);

function failure(detail: unknown): ApiError {
    return new ApiError('x', 502, null, { detail });
}

describe('problemText', () => {
    it('adds the providers own sentence after the catalog words', () => {
        const e = failure({ code: 'provider_unreachable', reason: 'The bridge is starting.' });
        expect(refusalReason(e)).toBe('The bridge is starting.');
        expect(problemText(e, t)).toBe('the provider did not answer. (The bridge is starting.)');
    });
    it('leaves the words alone when there is no reason', () => {
        expect(problemText(failure({ code: 'provider_unreachable' }), t)).toBe('the provider did not answer.');
    });
});

describe('refresh after a write (u144-01)', () => {
    it('a refresh asked while an older read is in flight shows data from AFTER the write', async () => {
        let serverProviders = [{ id: 'old' }];
        const held: Array<() => void> = [];
        const fetcher = (async (path: string) => {
            const snapshot = serverProviders;
            if (path.endsWith('/providers') && held.length === 0) await new Promise<void>((r) => held.push(r));
            if (path.endsWith('/providers')) return { providers: snapshot };
            if (path.endsWith('/conversations')) return { conversations: [] };
            if (path.endsWith('/bindings')) return { bindings: [] };
            return { messages: [] };
        }) as never;
        const stop = attach(fetcher);
        await Promise.resolve();
        serverProviders = [{ id: 'new' }];
        const afterWrite = refresh();
        held[0]?.();
        await afterWrite;
        expect((messaging.providers as Array<{ id: string }>).map((p) => p.id)).toEqual(['new']);
        stop();
    });
});
