import type { Inspection, Message } from './model';
import type { Tab } from './model';

interface Stored {
  tab: Tab;
  earlier: boolean;
  approved: boolean;
  scroll: number;
  since: string | null;
}

const records = new Map<number, Stored>();

export function inspectionOf(id: number, messages: () => readonly Message[]): Inspection {
  let record = records.get(id);
  if (!record) {
    const made = $state<Stored>({ tab: 'action', earlier: false, approved: false, scroll: 0, since: messages().find((m) => m.by === 'agent' && !m.read)?.id ?? null });
    records.set(id, made);
    record = made;
  }
  const stored = record;
  return {
    get tab() { return stored.tab; }, set tab(value: Tab) { stored.tab = value; },
    get earlier() { return stored.earlier; }, set earlier(value: boolean) { stored.earlier = value; },
    get approved() { return stored.approved; }, set approved(value: boolean) { stored.approved = value; },
    get scroll() { return stored.scroll; }, set scroll(value: number) { stored.scroll = value; },
    get boundary() { return messages().findIndex((m) => (stored.since === null ? m.by === 'agent' && !m.read : m.id === stored.since)); },
    set boundary(_value: number) {  },
  };
}

export function resetInspections(): void {
  records.clear();
}
