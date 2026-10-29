import { describe, expect, test } from 'vitest';

import { consentBlock, isScriptFile, needsScriptConsent, scriptFiles } from './scripts';

describe('which files are executable', () => {
    test('a recorded mode bit says so', () => {
        expect(isScriptFile({ path: 'run', exec: true })).toBe(true);
    });

    test('so does the `scripts/` prefix, with or without a leading ./', () => {
        expect(isScriptFile({ path: 'scripts/run.sh' })).toBe(true);
        expect(isScriptFile({ path: './scripts/run.sh' })).toBe(true);
    });

    test('an ordinary member is not, whatever it is called', () => {
        expect(isScriptFile({ path: 'SKILL.md' })).toBe(false);
        expect(isScriptFile({ path: 'docs/example.sh' })).toBe(false);
        expect(isScriptFile({ path: 'scriptsy/run' })).toBe(false);
    });

    test('a member with no path, or none at all, is not a script', () => {
        expect(isScriptFile({ path: '   ' })).toBe(false);
        expect(isScriptFile(null)).toBe(false);
        expect(isScriptFile(undefined)).toBe(false);
    });

    test('`exec: false` does not veto the prefix', () => {
        expect(isScriptFile({ path: 'scripts/run', exec: false })).toBe(true);
    });
});

describe('when the checkbox is raised', () => {
    test('a preview LISTING an executable member raises it', () => {
        const preview = { files: [{ path: 'SKILL.md' }, { path: 'scripts/run.sh' }] };
        expect(needsScriptConsent(preview)).toBe(true);
        expect(scriptFiles(preview).map((file) => file.path)).toEqual(['scripts/run.sh']);
    });

    test('a preview listing only ordinary members does NOT', () => {
        expect(needsScriptConsent({ files: [{ path: 'SKILL.md' }] })).toBe(false);
    });

    test('a preview with no file list at all does NOT, and says nothing either way', () => {
        expect(needsScriptConsent({})).toBe(false);
        expect(needsScriptConsent(null)).toBe(false);
        expect(scriptFiles({ files: 'lots' as never })).toEqual([]);
    });
});

describe('the consent block', () => {
    test('it names the whole digest and the sha of the text that was shown', () => {
        expect(consentBlock({ digest: 'abc123', body_sha: 'def456' })).toEqual({
            digest: 'abc123',
            body_sha: 'def456',
            scripts: true,
        });
    });

    test('a MISSING digest or body sha answers null: no consent with a hole in it', () => {
        expect(consentBlock({ digest: 'abc123' })).toBeNull();
        expect(consentBlock({ body_sha: 'def456' })).toBeNull();
        expect(consentBlock({ digest: '   ', body_sha: 'def' })).toBeNull();
        expect(consentBlock(null)).toBeNull();
    });

    test('a digest PREFIX is never substituted for a digest', () => {
        expect(consentBlock({ digest_prefix: 'abc1', body_sha: 'def' })).toBeNull();
    });

    test('NEGATIVE CONTROL: the builder can answer', () => {
        expect(consentBlock({ digest: 'a', body_sha: 'b' })).not.toBeNull();
    });
});

describe('an MCP server owes the consent tick (#1811)', () => {
    const server = { name: 'rea', command: 'npx', args: ['-y', 'rea-agents@6.5.0', 'mcp'], env_keys: ['REA_TOKEN'] };

    test('raises the gate with no script file at all', () => {
        expect(needsScriptConsent({ files: [{ path: '.claude-plugin/plugin.json' }], mcp_servers: [server] })).toBe(true);
        expect(needsScriptConsent({ files: [{ path: '.claude-plugin/plugin.json' }], mcp_servers: [] })).toBe(false);
    });

    test('prints the whole command line', async () => {
        const { mcpCommandLine } = await import('./mcp');
        expect(mcpCommandLine(server)).toBe('npx -y rea-agents@6.5.0 mcp');
        expect(mcpCommandLine({ ...server, args: ['-c', 'a b'] })).toBe("npx -c 'a b'");
    });
});
