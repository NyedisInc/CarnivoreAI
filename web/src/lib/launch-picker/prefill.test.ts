import { describe, expect, it } from 'vitest';
import { nextFreeName, prefillFor, shortTaskName } from './prefill';

describe('launch picker prefill', () => {
    it('a project gives its name and starts unpinned', () => {
        expect(prefillFor({ kind: 'project', name: 'Carnivore' }, ['Carnivore'])).toEqual({ name: 'Carnivore', pinned: false });
    });
    it('a session gives its name with the next free number, never a taken one', () => {
        expect(prefillFor({ kind: 'session', name: 'Carnivore', pinned: true }, ['Carnivore'])).toEqual({ name: 'Carnivore 2', pinned: true });
        expect(nextFreeName('Carnivore', ['Carnivore', 'carnivore 2', 'Carnivore 3'])).toBe('Carnivore 4');
        expect(nextFreeName('Carnivore 2', ['Carnivore', 'Carnivore 2'])).toBe('Carnivore 3');
        expect(nextFreeName('Fresh', ['Other'])).toBe('Fresh');
    });
    it('a session that is not pinned starts unticked', () => {
        expect(prefillFor({ kind: 'session', name: 'A' }, []).pinned).toBe(false);
    });
    it('a task gives a short form of its title', () => {
        const got = prefillFor({ kind: 'task', title: 'New agent: prefilled name and pinned box under the agent chooser' }, []);
        expect(got.name.length).toBeLessThanOrEqual(40);
        expect(got.name.startsWith('New agent: prefilled name')).toBe(true);
        expect(shortTaskName('Short one\nsecond line')).toBe('Short one');
    });
    it('no source is an empty name, the server default, and unticked', () => {
        expect(prefillFor(null, ['x'])).toEqual({ name: '', pinned: false });
    });
});
