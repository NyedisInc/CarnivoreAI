import { describe, expect, test } from 'vitest';

import { toastFor } from './shape-toast';

describe('toastFor', () => {
  test('a frame becomes a local, session-less card naming the kind and the problems', () => {
    const toast = toastFor(
      { file_kind: 'pid_registry', contract_version: 1, problems: ['required key status absent'] },
      5,
    );
    expect(toast).toMatchObject({ id: 'shape:pid_registry:5', session_id: null, local: true, kind: 'ShapeUnrecognized' });
    expect(toast?.body).toBe('pid_registry v1: required key status absent');
    expect(toast?.title).toBe('claude code file shape changed');
  });

  test('a long problem list is summarised, and non-strings are dropped', () => {
    const toast = toastFor({ file_kind: 'transcript_line', contract_version: 1, problems: ['a', 'b', 'c', 'd', 'e', 7] });
    expect(toast?.body).toBe('transcript_line v1: a; b; c and 2 more');
  });

  test('a frame naming no file kind raises nothing', () => {
    expect(toastFor({ problems: ['x'] })).toBeNull();
  });
});
