import { expect, test } from 'vitest';
import { SESSIONS_TOP, projectOfHash, sessionsRouteOfHash } from './sessions-route';

test('the sessions fragments are unchanged', () => {
  expect(sessionsRouteOfHash('#sessions')).toEqual(SESSIONS_TOP);
  expect(sessionsRouteOfHash('#sessions/ab')).toEqual({ session: 'ab' });
  expect(projectOfHash('#sessions/ab')).toBeNull();
  expect(sessionsRouteOfHash('#settings')).toBeNull();
});

test('every old #projects link lands on the page: a project link names the project, a session link opens its panel', () => {
  expect(sessionsRouteOfHash('#projects')).toEqual(SESSIONS_TOP);
  expect(projectOfHash('#projects')).toBeNull();
  expect(projectOfHash('#projects/3')).toBe('3');
  expect(sessionsRouteOfHash('#projects/3')).toEqual(SESSIONS_TOP);
  expect(projectOfHash('#projects/c/orphaned/3')).toBe('3');
  expect(projectOfHash('#projects/c')).toBeNull();
  expect(sessionsRouteOfHash('#projects/c/7/3/ab')).toEqual({ session: 'ab' });
  expect(sessionsRouteOfHash('#projects/3/ab')).toEqual({ session: 'ab' });
  expect(sessionsRouteOfHash('#projects/%E0%A4%A')).toEqual(SESSIONS_TOP);
});
