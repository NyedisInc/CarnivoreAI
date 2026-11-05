import { describe, expect, it } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { errorText as saveErrorText } from '../../cplugs/save/settings-api';
import { refusalText as labRefusalText } from '../../cplugs/devwidgetlab/lab-api';
import { refusalText as automationsRefusalText } from '../automations/format';
import { errorText as launchProfilesErrorText } from '../launch-profiles-page/api';
import { refusalText as modsRefusalText } from '../mods/mods-format';
import { errorText as panelErrorText } from '../settings-page/panel-kit/error-text';
import { apiErrorMessageOr, errorMessageOr, failureDetail, failureReason, nonEmptyErrorMessageOr, MAX_LISTED_FILES, refusedFiles, withRefusedFiles } from './failure-reason';

describe('failure-reason', () => {
  it('errorMessageOr keeps an empty Error message and falls back for non-errors', () => {
    expect(errorMessageOr(new Error('gone'), 'f')).toBe('gone');
    expect(errorMessageOr(new Error(''), 'f')).toBe('');
    expect(errorMessageOr('boom', 'f')).toBe('f');
  });
  it('nonEmptyErrorMessageOr falls back on an empty message', () => {
    expect(nonEmptyErrorMessageOr(new Error('gone'), 'f')).toBe('gone');
    expect(nonEmptyErrorMessageOr(new Error(''), 'f')).toBe('f');
    expect(nonEmptyErrorMessageOr(null, 'f')).toBe('f');
  });
  it('apiErrorMessageOr trusts only an ApiError sentence', () => {
    expect(apiErrorMessageOr(new ApiError('nope', 400, null), 'f')).toBe('nope');
    expect(apiErrorMessageOr(new Error('plain'), 'f')).toBe('f');
  });
});

const SAME_DETAIL_PAYLOADS: readonly unknown[] = [
  { detail: 'the folder moved' },
  { detail: { code: 'x', detail: 'the folder moved' } },
  { detail: { message: 'the folder moved' } },
];
const refused = (payload: unknown): ApiError => new ApiError('HTTP 409', 409, null, payload);

describe('one detail rule (site review ERR-8)', () => {
  it.each(SAME_DETAIL_PAYLOADS.map((payload) => [JSON.stringify(payload), payload] as const))(
    'every call site says the same sentence for the same server detail: %s',
    (_name, payload) => {
      const error = refused(payload);
      const sentences = [
        saveErrorText(error), panelErrorText(error), launchProfilesErrorText(error),
        modsRefusalText(error), automationsRefusalText(error), labRefusalText(error), failureReason(error),
      ];
      expect(sentences).toEqual(sentences.map(() => 'the folder moved'));
    },
  );
  it('reads a validation list as where: why lines, strings or loc/msg rows', () => {
    expect(failureDetail(refused({ detail: ['a: b', 'c: d'] }))).toBe('a: b; c: d');
    expect(failureDetail(refused({ detail: [{ loc: ['body', 'env', 0], msg: 'bad' }] }))).toBe('env.0: bad');
  });
  it('falls back to the error message, then to the string of a non-error, and has no detail for either', () => {
    expect(failureReason(refused(null))).toBe('HTTP 409');
    expect(failureReason(new Error('plain'))).toBe('plain');
    expect(failureReason('boom')).toBe('boom');
    expect(failureDetail(new Error('plain'))).toBe('');
  });
});

describe('refusal files', () => {
  const body = (files: unknown[], more = 0): unknown => ({ detail: { code: 'unscannable_files', files, files_more: more } });
  const refused = new ApiError('nothing was published.', 409, 'unscannable_files', body(['a.bin', 'b/c.txt', 7]));
  const words = (key: string, params?: Record<string, unknown> | null): string =>
    key === 'pack.refused.files_more' ? `files: ${params?.['files']} and ${params?.['count']} more` : `files: ${params?.['files']}`;
  it('refusedFiles reads the named paths and ignores anything else', () => {
    expect(refusedFiles(refused)).toEqual({ files: ['a.bin', 'b/c.txt'], more: 0 });
    expect(refusedFiles(new ApiError('x', 409, null, { detail: 'plain' }))).toEqual({ files: [], more: 0 });
    expect(refusedFiles(new Error('x'))).toEqual({ files: [], more: 0 });
  });
  it('refusedFiles caps the list and counts the rest, the server count included', () => {
    const many = Array.from({ length: MAX_LISTED_FILES + 5 }, (_, i) => `f${i}`);
    expect(refusedFiles(new ApiError('x', 409, null, body(many, 3)))).toEqual({ files: many.slice(0, MAX_LISTED_FILES), more: 8 });
  });
  it('withRefusedFiles appends the list, with "and N more", only when files are named', () => {
    expect(withRefusedFiles('nothing was published.', refused, words)).toBe('nothing was published. files: a.bin, b/c.txt');
    expect(withRefusedFiles('nothing was published.', new ApiError('x', 409, null, body(['a.bin'], 4)), words)).toBe('nothing was published. files: a.bin and 4 more');
    expect(withRefusedFiles('nothing was published.', new Error('x'), words)).toBe('nothing was published.');
  });
});
