import { describe, expect, it } from 'vitest';
import { buildOpenProjectPayload } from '../launchpad/open-project-payload';
import { branchFromName, initialCopy, worktreeAnswer } from './worktree-model';

describe('the launch picker worktree row (#2727)', () => {
    it('starts the branch from the name, never pre-ticks a secret, and rides the local create body only', () => {
        expect(branchFromName('Fix Login Bug')).toBe('wt/fix-login-bug');
        expect(branchFromName('  ')).toBe('');
        const probe = { repo: true, file: { sha256: 'a', setup: [], text: '', approved: false, copy: [{ name: '.env', secret: true }, { name: 'local.json', secret: false }] } };
        expect(initialCopy(probe)).toEqual(['local.json']);
        expect(worktreeAnswer(false, 'x', '', false, [])).toBeNull();
        expect(worktreeAnswer(true, '  ', '', false, [])).toBeNull();
        const wt = worktreeAnswer(true, ' feat/x ', '', true, ['local.json']);
        expect(wt).toEqual({ branch: 'feat/x', base_branch: null, setup: true, copy: ['local.json'] });
        expect(buildOpenProjectPayload('app', '/code/app', { worktree: wt }, {}).worktree).toEqual(wt);
        expect(buildOpenProjectPayload('app', 'ssh://studio/code/app', { worktree: wt }, {}).worktree).toBeUndefined();
    });
});
