import type { SessionGitStatus } from '../../api/types';

export type FilesGlance =
  | { kind: 'changed'; count: number }
  | { kind: 'clean' }
  | { kind: 'no_repo' }
  | { kind: 'remote' }
  | { kind: 'unread' };

export function glanceOf(git: SessionGitStatus | null): FilesGlance {
  if (!git) return { kind: 'unread' };
  switch (git.state) {
    case 'ok': {
      const count = git.files.length + git.truncated;
      return count > 0 ? { kind: 'changed', count } : { kind: 'clean' };
    }
    case 'not_a_repo': return { kind: 'no_repo' };
    case 'remote': return { kind: 'remote' };
    default: return { kind: 'unread' };
  }
}

export function glanceWords(glance: FilesGlance): { key: string; vars?: Record<string, number> } {
  return glance.kind === 'changed' ? { key: 'glance.changed', vars: { n: glance.count } } : { key: `glance.${glance.kind}` };
}
