import { describe, expect, it } from 'vitest';
import { renameState } from './row-text';
import type { RowHost } from './row-host';

const host = {} as RowHost;

describe('renameState for an asleep row', () => {
    it('is renameable with a session_uuid', () => {
        expect(renameState({ name: 'a', asleep: true, session_uuid: 'u1', session_id: null }, host).state).toBe('renameable');
    });
    it('stays unavailable when archived or without a uuid', () => {
        expect(renameState({ name: 'a', asleep: true, session_uuid: 'u1', archived: true }, host).state).toBe('unavailable');
        expect(renameState({ name: 'a', asleep: true, session_id: null }, host).state).toBe('unavailable');
    });
});

describe('renameState for a live row (item 66)', () => {
    it('a live session id means renameable', () => {
        expect(renameState({ name: 'a', session_id: 'sess-1', created_by_cloude: true }, host).state).toBe('renameable');
    });
    it('no id but known ownership is unavailable, and open differs from adopt', () => {
        const ours = renameState({ name: 'a', session_id: null, created_by_cloude: true }, host);
        const theirs = renameState({ name: 'a', session_id: null, created_by_cloude: false }, host);
        expect(ours.state).toBe('unavailable');
        expect(theirs.state).toBe('unavailable');
        expect(ours.reason).not.toBe(theirs.reason);
        expect(ours.reason).toMatch(/open/);
        expect(theirs.reason).toMatch(/adopt/);
    });
    it('null or undefined ownership is unknown and says CANNOT DETERMINE', () => {
        for (const v of [null, undefined]) {
            const st = renameState({ name: 'a', session_id: null, created_by_cloude: v }, host);
            expect(st.state).toBe('unknown');
            expect(st.reason).toMatch(/CANNOT DETERMINE/);
        }
    });
});
