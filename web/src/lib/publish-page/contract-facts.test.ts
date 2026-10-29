import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { parseFacts } from './api-facts';

const golden = JSON.parse(
    readFileSync(fileURLToPath(new URL('../../../../tests/fixtures/publish_page/item_facts.json', import.meta.url)), 'utf8'),
) as Record<string, unknown>;

describe('parseFacts', () => {
    it('reads the golden facts answer with every field defined', () => {
        const facts = parseFacts(golden, 'skill:my-skill');
        expect(facts).toMatchObject({
            location: 'skill:my-skill', kind: 'skill', name: 'my-skill', harness: 'claude', declared_version: '1.4.0',
            file_count: 3, total_bytes: 142, license_file: true, license: 'MIT', grade: 'B', description_tokens_est: 12,
            changed_files: 0, changed_at: '', made_at: '2025-10-09T08:53:20Z',
        });
        expect(facts.files.map((f) => f.path)).toEqual(['LICENSE', 'SKILL.md', 'notes/more.md']);
        expect(facts.sends[0]).toEqual({
            submission_id: 'a'.repeat(32), version: '1.4.0', sent_at: '2025-10-09T08:56:40Z', hero: '', media_submission_id: '', hero_sha: '',
        });
        expect(facts.checks[0]).toEqual({ version: '1.4.0', ok: true, at: '2025-10-09T08:55:00Z', summary: 'clean', grade: 'B', files: 3, bytes: 142, digest: '7f82dc8cabbce9ed3e3c58e276c373f89fd5c87d166196fd43e999097a5f70b9', findings: [] });
        for (const [key, value] of Object.entries(facts)) expect(value, key).not.toBeUndefined();
    });

    it('keeps a stored refusal file paths and drops a finding without one (X5-53)', () => {
        const facts = parseFacts({ checks: [{ version: '1.0.0', ok: false, at: 'x', summary: 'secret_found', findings: [{ code: 'secret_found', path: 'scripts/render.sh' }, { code: 'hidden_file', path: '' }, 7] }] }, 'x');
        expect(facts.checks[0]?.findings).toEqual([{ code: 'secret_found', path: 'scripts/render.sh' }]);
        expect(facts.checks[0]?.digest).toBe('');
    });

    it('keeps an empty answer empty rather than inventing values', () => {
        expect(parseFacts({}, 'x')).toMatchObject({ declared_version: '', changed_files: 0, files: [], sends: [], checks: [] });
    });
});
