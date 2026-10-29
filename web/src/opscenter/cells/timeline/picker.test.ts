import { expect, it } from 'vitest';
import { pickValueFor, pickedInfo } from './picker';
import type { SessionInfo } from '../../api';

const row = (id: string, rowId: number | null): SessionInfo => ({ session: { id }, session_row_id: rowId }) as unknown as SessionInfo;

it('the value is the row, and survives a new app id for the same row', () => {
  const value = pickValueFor(row('ses_old', 7));
  expect(value).toBe('row:7');
  expect(pickedInfo([row('ses_new', 7)], value)?.session.id).toBe('ses_new');
});
it('a pick stored by the first drawing (a bare app id) still resolves', () => {
  expect(pickedInfo([row('ses_a', 3)], 'ses_a')?.session_row_id).toBe(3);
});
it('an empty or unmatched pick resolves to nothing', () => {
  expect(pickedInfo([row('ses_a', 3)], '')).toBeNull();
  expect(pickedInfo([row('ses_a', 3)], 'row:9')).toBeNull();
});
