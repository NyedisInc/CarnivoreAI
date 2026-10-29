
import { t } from '../i18n/index.svelte';

export function codeWords(code: string): string {
  return /^\d{6}$/.test(code) ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

export function countdown(expiresAt: string | null, nowMs: number): string {
  const left = expiresAt === null ? 0 : Math.max(0, Math.floor((Date.parse(expiresAt) - nowMs) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}

export function passed(expiresAt: string | null, nowMs: number): boolean {
  return expiresAt === null || Date.parse(expiresAt) <= nowMs;
}

export function ageWords(at: string | null, nowMs: number): string {
  if (at === null || Number.isNaN(Date.parse(at))) return t('computers.row.never_seen');
  const secs = Math.max(0, Math.floor((nowMs - Date.parse(at)) / 1000));
  if (secs < 60) return t('computers.age.seconds', { count: secs });
  if (secs < 3600) return t('computers.age.minutes', { count: Math.floor(secs / 60) });
  if (secs < 86400) return t('computers.age.hours', { count: Math.floor(secs / 3600) });
  return t('computers.age.days', { count: Math.floor(secs / 86400) });
}

export function stateWords(state: string): string {
  if (state === 'waiting_first_link') return t('computers.row.waiting_first_link');
  if (state === 'refused') return t('computers.row.refused');
  const key = `hosts.peer.state.${state}`;
  const words = t(key);
  return words === key ? state : words;
}

export function codeCopy(prefix: string, code: string, generic: string): string {
  const key = `${prefix}.${code}`;
  const words = t(key);
  return words === key ? t(generic) : words;
}

export function dialWords(computer: { label: string; dial?: { state: string; since: string | null } | null; firewall_on?: boolean }): string | null {
  const dial = computer.dial;
  if (!dial || dial.state === 'linked') return null;
  const label = computer.label;
  if (dial.state === 'unreachable') {
    const at = dial.since === null ? NaN : Date.parse(dial.since);
    const base = Number.isNaN(at)
      ? t('computers.dial.unreachable_untimed', { label })
      : t('computers.dial.unreachable', { label, time: new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) });
    return computer.firewall_on ? `${base} ${t('computers.dial.firewall', { label })}` : base;
  }
  const key = `computers.dial.${dial.state}`;
  const words = t(key, { label });
  return words === key ? null : words;
}
