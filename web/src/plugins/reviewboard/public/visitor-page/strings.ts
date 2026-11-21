import slice from '../../catalog.en.js';

const MESSAGES = slice as Record<string, unknown>;

export function t(key: string, params: Record<string, string | number> = {}): string {
  const message = MESSAGES[key];
  if (typeof message !== 'string') return key;
  return message.replace(/\{(\w+)\}/g, (whole, name: string) => (name in params ? String(params[name]) : whole));
}
