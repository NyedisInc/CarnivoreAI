import { beforeEach, describe, expect, it, vi } from 'vitest';

const rows = vi.hoisted(() => ({ list: [] as unknown[] }));
vi.mock('../../opscenter/api/poll.svelte', () => ({ listingRows: async () => rows.list }));
vi.mock('../drawer/group-membership', () => ({ uuidOfName: () => null }));

import { sessionIdForUuid, sessionRefFor, sessionUuidFor } from './session-ref';
import { sessionUuidOfRow } from '../../opscenter/api/automations-widget.svelte';

beforeEach(() => {
    rows.list = [{ session_row_id: 12, session_uuid: 'u-12', tmux_session: 'carnivore_a', session: { id: 'ses_1' } }];
});

describe('session-ref reads the wrapper', () => {
    it('sessionRefFor carries the uuid', async () => {
        expect(await sessionRefFor('ses_1')).toEqual({ sessionId: 'ses_1', sessionRowId: 12, sessionUuid: 'u-12', tmuxName: 'carnivore_a' });
    });
    it('sessionUuidFor answers from the ref with no lookup', async () => {
        expect(await sessionUuidFor({ sessionUuid: 'u-x', sessionRowId: 12 })).toBe('u-x');
    });
    it('sessionUuidOfRow reads the listing', async () => {
        expect(await sessionUuidOfRow(12)).toBe('u-12');
        expect(await sessionUuidOfRow(99)).toBeNull();
    });
    it('sessionIdForUuid maps a uuid to the live session id through the listing', async () => {
        expect(await sessionIdForUuid('u-12')).toBe('ses_1');
        expect(await sessionIdForUuid('u-none')).toBeNull();
    });
});
