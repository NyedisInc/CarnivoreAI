import { expect, it } from 'vitest';
import { wakeArmKey } from './wake-arm.svelte';

it('keys on the uuid when there is one, the name otherwise', () => {
    expect(wakeArmKey('carnivore_X', 'p:1', 'u-a')).toBe('u-a|p:1');
    expect(wakeArmKey('carnivore_X', 'p:1', 'u-a')).not.toBe(wakeArmKey('carnivore_X', 'p:1', 'u-b'));
    expect(wakeArmKey('carnivore_X', null)).toBe('carnivore_X|');
});
