import { t } from '../i18n/index.svelte';

export function errorCodeOf(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const record = body as Record<string, unknown>;
  if (typeof record['code'] === 'string' && record['code']) return record['code'];
  const detail = record['detail'];
  if (detail && typeof detail === 'object') {
    const inner = (detail as Record<string, unknown>)['code'];
    if (typeof inner === 'string' && inner) return inner;
  }
  return null;
}

export function paramsOf(body: unknown): Record<string, string> {
  const detail = body && typeof body === 'object' ? (body as Record<string, unknown>)['detail'] : null;
  const raw = detail && typeof detail === 'object' ? (detail as Record<string, unknown>)['params'] : null;
  if (!raw || typeof raw !== 'object') return {};
  return Object.fromEntries(Object.entries(raw).filter((entry): entry is [string, string] => typeof entry[1] === 'string'));
}

export function codedSentence(body: unknown, fallback: string): string {
  const code = errorCodeOf(body);
  if (!code) return fallback;
  const key = `api.error.${code}`;
  const sentence = t(key, paramsOf(body));
  return sentence && sentence !== key ? sentence : fallback;
}
