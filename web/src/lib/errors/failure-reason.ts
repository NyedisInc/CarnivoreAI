import { ApiError } from '../../opscenter/api/auth.svelte';
import type { Translate } from '../sessions/types';
import { detailOfBody } from './detail-of-body';

export function errorMessageOr(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function nonEmptyErrorMessageOr(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function apiErrorMessageOr(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

function validationLines(detail: unknown): string {
  if (!Array.isArray(detail)) return '';
  const lines = detail.map((row) => {
    if (typeof row === 'string') return row;
    const { loc, msg } = (row ?? {}) as { loc?: unknown[]; msg?: unknown };
    const where = (Array.isArray(loc) ? loc : []).filter((part) => part !== 'body').join('.');
    const why = typeof msg === 'string' ? msg : '';
    return where && why ? `${where}: ${why}` : why;
  });
  return lines.filter(Boolean).join('; ');
}

export function failureDetail(error: unknown): string {
  if (!(error instanceof ApiError)) return '';
  const body = error.payload as { detail?: unknown } | null;
  return validationLines(body?.detail) || detailOfBody(body);
}

export function failureReason(error: unknown): string {
  return failureDetail(error) || (error instanceof Error ? error.message : String(error));
}

export const MAX_LISTED_FILES = 20;

export interface RefusedFiles {
  files: string[];
  more: number;
}

export function refusedFiles(error: unknown): RefusedFiles {
  if (!(error instanceof ApiError)) return { files: [], more: 0 };
  const detail = (error.payload as { detail?: { files?: unknown; files_more?: unknown } } | null)?.detail;
  const named = Array.isArray(detail?.files) ? detail.files.filter((file): file is string => typeof file === 'string') : [];
  const serverMore = typeof detail?.files_more === 'number' && detail.files_more > 0 ? detail.files_more : 0;
  return { files: named.slice(0, MAX_LISTED_FILES), more: serverMore + Math.max(0, named.length - MAX_LISTED_FILES) };
}

export function withRefusedFiles(sentence: string, error: unknown, t: Translate): string {
  const { files, more } = refusedFiles(error);
  if (!files.length) return sentence;
  const list = files.join(', ');
  return `${sentence} ${more ? t('pack.refused.files_more', { files: list, count: more }) : t('pack.refused.files', { files: list })}`;
}
