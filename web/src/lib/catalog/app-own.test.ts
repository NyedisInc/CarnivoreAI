import { describe, expect, test } from 'vitest';
import { isAppOwnSource, isBuiltinPlugin, isBuiltinTheme, isBundledSkill } from './app-own';

describe('what the warez page treats as the app\'s own', () => {
    test('ledger sources', () => {
        expect([isAppOwnSource('builtin'), isAppOwnSource('bundled'), isAppOwnSource('https://index.example/v1'), isAppOwnSource(null)]).toEqual([true, true, false, false]);
    });
    test('themes, plugins and skills', () => {
        expect([isBuiltinTheme('builtin'), isBuiltinTheme('user')]).toEqual([true, false]);
        expect([isBuiltinPlugin('builtin'), isBuiltinPlugin('core'), isBuiltinPlugin('dev'), isBuiltinPlugin('')]).toEqual([true, true, false, false]);
        expect([isBundledSkill(['carnivore/huddle']), isBundledSkill(['acme/deploy', null]), isBundledSkill([])]).toEqual([true, false, false]);
    });
});
