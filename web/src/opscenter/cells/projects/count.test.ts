import { describe, expect, it } from 'vitest';
import { countForProject } from './count';
import type { ProjectResponse, SessionInfo } from '../../api';

const rows = [{ project_id: 3 }, { project_id: 3 }, { project_id: 4 }] as unknown as SessionInfo[];

describe('countForProject', () => {
  it('counts the rows filed under the project id', () => {
    expect(countForProject(rows, { id: 3 } as unknown as ProjectResponse)).toBe(2);
  });
  it('is null, not 0, for a project with no id', () => {
    expect(countForProject(rows, { id: null } as unknown as ProjectResponse)).toBeNull();
  });
});
