import { ApiError } from '../../opscenter/api/auth.svelte';

export function errorMessageOr(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function nonEmptyErrorMessageOr(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function apiErrorMessageOr(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}
