import { describe, expect, it } from 'vitest';
import { filterRowsByHost, hostOffKey, offMachineIds, type FilterMachine } from './pack-filter';

const ROSTER: FilterMachine[] = [
    { install_id: 'n-id', is_self: true, host_key: 'local' },
    { install_id: 't-id', is_self: false, host_key: 'peer-hosta' },
];
const ROWS = [
    { name: 'a-local', host_key: 'local' },
    { name: 'b-unkeyed' },
    { name: 'c-hosta', host_key: 'peer-hosta' },
    { name: 'd-stranger', host_key: 'peer-unknown' },
];
const names = (off: string[]): string[] => filterRowsByHost(ROWS, ROSTER, offMachineIds(off.map(hostOffKey))).map((r) => r.name);

describe('filterRowsByHost', () => {
    it('shows every row while every computer is on', () => {
        expect(names([])).toEqual(['a-local', 'b-unkeyed', 'c-hosta', 'd-stranger']);
    });
    it('hosta off hides hosta rows and keeps this computer and unplaceable rows', () => {
        expect(names(['t-id'])).toEqual(['a-local', 'b-unkeyed', 'd-stranger']);
    });
    it('this computer off hides local and unkeyed rows only', () => {
        expect(names(['n-id'])).toEqual(['c-hosta', 'd-stranger']);
    });
    it('both off hides both, and a project mixing them keeps only the rows of the computer that is on', () => {
        expect(names(['n-id', 't-id'])).toEqual(['d-stranger']);
        expect(names(['t-id']).filter((n) => n !== 'd-stranger')).toEqual(['a-local', 'b-unkeyed']);
    });
    it('reads only host-off keys out of a fold list', () => {
        expect([...offMachineIds(['pack', 'p:1', hostOffKey('t-id')])]).toEqual(['t-id']);
    });
});
