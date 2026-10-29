import { describe, expect, test } from 'vitest';
import { EXAMPLES, exampleForm, offeredExamples } from './examples';
import { formToProfile } from './form-model';
import type { ProfileRow } from './api';

const row = (harness: string, installed: boolean): ProfileRow => ({ id: harness, harness, installed } as ProfileRow);

describe('examples', () => {
    test('the four examples: claude with a model, claude via openrouter, a plain shell, codex', () => {
        expect(EXAMPLES.map((e) => e.id)).toEqual(['claude_model', 'claude_openrouter', 'shell', 'codex']);
    });
    test('claude with a model builds a fixed-model profile with its flag', () => {
        const p = formToProfile(exampleForm(EXAMPLES[0]!, 'claude with a model', []));
        expect(p.harness).toBe('claude');
        expect(p.model).toEqual({ mode: 'fixed', value: 'sonnet' });
        expect(p.flags).toEqual(['--verbose']);
    });
    test('the openrouter example picks the first enabled openrouter connection', () => {
        const form = exampleForm(EXAMPLES[1]!, 'x', [{ id: 'or1', preset: 'openrouter', label: 'or', enabled: true, has_key: true, key_hint: '' }]);
        expect(form.endpointMode).toBe('connection');
        expect(form.connectionId).toBe('or1');
        expect(form.modelMode).toBe('ask');
    });
    test('first run offers only installed agents plus the shell, and never an example that needs a connection', () => {
        const only = offeredExamples([row('claude', true), row('codex', false)]).map((e) => e.id);
        expect(only).toEqual(['claude_model', 'shell']);
        expect(offeredExamples([row('claude', true), row('codex', true)]).map((e) => e.id)).toEqual(['claude_model', 'shell', 'codex']);
    });
});
