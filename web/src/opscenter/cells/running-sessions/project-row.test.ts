import { describe, expect, it } from 'vitest';
import { majorityProject, projectOfRow } from './project';
import type { ProjectResponse, SessionInfo } from '../../api';

function info(dir: string, wrapper: { project_id?: number | null; project_name?: string | null } = {}): SessionInfo {
  return { session: { working_dir: dir }, ...wrapper } as unknown as SessionInfo;
}

const projects = [{ id: 7, name: 'gamma', root: '/p/gamma', path: '/p/gamma' }] as unknown as ProjectResponse[];

describe('projectOfRow', () => {
  it('prefers the wrapper project_name over the folder leaf', () => {
    expect(projectOfRow(info('/x/beta', { project_name: 'alpha' }), [])).toBe('alpha');
  });
  it('joins project_id against the project list when the name is absent', () => {
    expect(projectOfRow(info('/x/beta', { project_id: 7 }), projects)).toBe('gamma');
  });
  it('falls back to the folder leaf when the wrapper names no project', () => {
    expect(projectOfRow(info('/x/beta'), [])).toBe('beta');
  });
});

describe('majorityProject over rows', () => {
  it('counts the wrapper project, not the folder', () => {
    const rows = [info('/a/one', { project_name: 'p' }), info('/b/two', { project_name: 'p' }), info('/c/three', { project_name: 'q' })];
    expect(majorityProject(rows, [])).toBe('p');
  });
});
