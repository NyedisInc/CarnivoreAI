import { describe, expect, test } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { Fetcher } from '../skills-page/skills-api';
import { restoreSkillMdVersion, saveSkillMd, StaleBaseError } from './skill-md-api';

const CTX = { projectPath: '/p/x', profile: 'work' } as never;

describe('skill-md api', () => {
    test('save and restore carry the project and profile in the query, never the body', async () => {
        const calls: { path: string; body: string }[] = [];
        const fetcher = (async (path: string, init?: { body?: string }) => {
            calls.push({ path, body: init?.body ?? '' });
            return { sha256: 's', version_id: 3 };
        }) as unknown as Fetcher;
        await saveSkillMd('loc', 'text', 'base', null, CTX, fetcher);
        await restoreSkillMdVersion('loc', 3, 'base', CTX, fetcher);
        for (const c of calls) {
            expect(c.path).toContain('?project_path=%2Fp%2Fx&profile=work');
            expect(c.body).not.toContain('project_path');
        }
    });

    test('only a stale 409 is a stale base; other 409s surface as the refusal', async () => {
        const failing = (payload: unknown) => (async () => { throw new ApiError('x', 409, null, payload); }) as unknown as Fetcher;
        await expect(saveSkillMd('l', 't', 'b', null, CTX, failing({ detail: { code: 'stale', current_sha256: 'n' }, current_sha256: 'n' }))).rejects.toBeInstanceOf(StaleBaseError);
        await expect(saveSkillMd('l', 't', 'b', null, CTX, failing({ detail: { code: 'too_large_to_edit', detail: 'big' } }))).rejects.toBeInstanceOf(ApiError);
    });
});
