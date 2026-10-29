import type { PlacementOptionValue } from '../../opscenter/widgets/placement-options';

export const MAX_OPTION_TEXT = 128;

export const OPTION_KEY_RE = /^[a-z][a-z0-9_]{0,31}$/;

export function normalizeOptionValues(raw: unknown, limit: number): Record<string, PlacementOptionValue> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const options: Record<string, PlacementOptionValue> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (Object.keys(options).length >= limit) break;
    if (!OPTION_KEY_RE.test(key)) continue;
    if (typeof value === 'boolean' || (typeof value === 'number' && Number.isInteger(value))) options[key] = value;
    else if (typeof value === 'string' && value.length <= MAX_OPTION_TEXT) options[key] = value;
  }
  return options;
}
