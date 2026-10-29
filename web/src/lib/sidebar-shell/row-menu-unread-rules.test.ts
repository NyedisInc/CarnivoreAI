/** @vitest-environment jsdom */
import { expect, it, vi } from 'vitest';

vi.mock('../plugins/session-card-actions', () => ({
    sessionCardMenuItems: () => [{ id: 'mark-unread', shortcut: 'U', label: 'mark unread', order: 200, locked: false }],
    runSessionCardAction: vi.fn(async () => true),
}));

import { contextFromRow } from '../item-menu/row-context';
import { rowMenuItems } from '../item-menu/menus/row';

const ids = (row: Record<string, unknown>): string[] =>
    rowMenuItems(contextFromRow({ name: 'carnivore_a', session_id: 'ses_1', ...row }, { surface: 'sidebar' })).map((i) => i.id);

it('mark unread is absent while working, mark read follows the unread flag on asleep rows too', () => {
    expect(ids({ status: 'working' })).not.toContain('mark-unread');
    expect(ids({ status: 'working_subagent' })).not.toContain('mark-unread');
    expect(ids({ status: 'idle' })).toContain('mark-unread');
    expect(ids({ status: 'asleep', asleep: true, session_uuid: 'u1', unread: true })).toContain('mark-read');
    expect(ids({ status: 'idle', unread: true })).toContain('mark-read');
    expect(ids({ status: 'idle', unread: false })).not.toContain('mark-read');
});
