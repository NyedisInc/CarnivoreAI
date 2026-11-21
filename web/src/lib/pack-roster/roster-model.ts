import type { ComputerEntry, ComputersView } from '../computers/computers-api';
import type { PackMachine, PackMachinesView, TakeoverReason } from '../pack-machines/pack-machines-store.svelte';
import type { DiscoveredMac, PeerRow } from '../hosts-page/federation-api';
import { machineKey, type HostRow } from '../hosts-page/hosts-adapter';

export type RosterKind = 'pack' | 'ssh-only' | 'paired-older';
export type FilterKey = 'all' | 'inpack' | 'overssh' | 'sshonly' | 'older' | 'unreach' | 'hostkey' | 'probe' | 'identity';
export const PACK_FILTERS: readonly FilterKey[] = ['all', 'inpack', 'overssh', 'sshonly', 'older'];
export const LOOK_FILTERS: readonly FilterKey[] = ['unreach', 'hostkey', 'probe', 'identity'];
export type SortKey = 'status' | 'name' | 'free' | 'seen';

export interface RosterComputer {
  id: string;
  name: string;
  kind: RosterKind;
  transport: 'local' | 'ssh' | 'tls';
  isSelf: boolean;
  isAlpha: boolean;
  machine: PackMachine | null;
  entry: ComputerEntry | null;
  host: HostRow | null;
  matchedBy: 'link' | 'target' | null;
  peer: PeerRow | null;
  hostKeys: string[];
  dial: string;
  since: string | null;
  lastSeen: string | null;
  viaRelay: boolean;
  needsUpdate: boolean;
  rank: number | null;
  eligible: boolean;
}

export interface RosterInputs {
  view: ComputersView | null;
  machines: readonly PackMachine[];
  hosts: readonly HostRow[];
  peers: readonly PeerRow[];
}

function dialOf(entry: ComputerEntry | null, isSelf: boolean): string {
  if (isSelf) return 'self';
  if (!entry) return 'never';
  if (entry.dial?.state) return entry.dial.state;
  return entry.state === 'connected' || entry.state === 'linked' ? 'linked' : entry.state === 'disconnected' ? 'unreachable' : 'never';
}

export function buildRoster(input: RosterInputs): RosterComputer[] {
  const entries = new Map((input.view?.computers ?? []).map((c) => [c.install_id, c]));
  const peerByIid = new Map(input.peers.map((p) => [p.peer_install_id, p]));
  const known = new Set<string>();
  const out: RosterComputer[] = [];
  const sshHosts = input.hosts.filter((h) => !h.local && !input.peers.some((p) => p.key === h.key));
  const claimed = new Set<string>();
  const hostFor = (id: string, name: string): { host: HostRow | null; by: 'link' | 'target' | null } => {
    const linked = sshHosts.find((h) => h.computer_install_id === id);
    if (linked) return { host: linked, by: 'link' };
    const guess = sshHosts.find((h) => !claimed.has(h.key) && !h.computer_install_id && machineKey(h.ssh_target) !== '' && machineKey(h.ssh_target) === machineKey(name));
    return guess ? { host: guess, by: 'target' } : { host: null, by: null };
  };
  const add = (machine: PackMachine | null, entry: ComputerEntry | null): void => {
    const id = machine?.install_id ?? entry?.install_id ?? '';
    if (id === '' || known.has(id)) return;
    known.add(id);
    const name = machine?.label || entry?.label || id.slice(0, 8);
    const isSelf = machine?.is_self === true || id === input.view?.self.install_id;
    const { host, by } = hostFor(id, name);
    if (host) claimed.add(host.key);
    const peer = peerByIid.get(id) ?? null;
    const local = input.hosts.find((h) => h.local) ?? null;
    out.push({
      id, name, kind: entry?.transport === 'ssh' && !isSelf && machine?.paired !== true ? 'paired-older' : 'pack',
      transport: isSelf ? 'local' : (entry?.transport ?? (peer ? 'tls' : 'ssh')), isSelf, isAlpha: machine?.is_master === true,
      machine, entry, host, matchedBy: by, peer,
      hostKeys: [...(isSelf && local ? [local.key] : []), ...(peer ? [peer.key] : []), ...(host ? [host.key] : [])],
      dial: dialOf(entry, isSelf), since: entry?.dial?.since ?? null, lastSeen: isSelf ? null : (entry?.last_link_at ?? null),
      viaRelay: machine?.link_path === 'relay', needsUpdate: !isSelf && machine?.paired === true && machine.roster_v1 === false,
      rank: machine?.rank ?? null, eligible: machine?.eligible === true,
    });
  };
  [...input.machines].sort((a, b) => Number(b.is_self) - Number(a.is_self)).forEach((m) => add(m, entries.get(m.install_id) ?? null));
  (input.view?.computers ?? []).forEach((c) => add(null, c));
  sshHosts.filter((h) => !claimed.has(h.key)).forEach((host) => {
    out.push({ id: `host:${host.key}`, name: host.label || host.key, kind: 'ssh-only', transport: 'ssh', isSelf: false, isAlpha: false, machine: null, entry: null,
      host, matchedBy: null, peer: null, hostKeys: [host.key], dial: 'ssh', since: null, lastSeen: host.probed_at,
      viaRelay: false, needsUpdate: false, rank: null, eligible: false });
  });
  return out;
}

export function lookFlags(c: RosterComputer): Record<'unreach' | 'hostkey' | 'probe' | 'identity', boolean> {
  const probe = c.host?.probe_state ?? '';
  return {
    unreach: ['unreachable', 'refused', 'local_network_blocked'].includes(c.dial) || c.entry?.state === 'disconnected',
    hostkey: probe === 'host_key_unknown' || c.dial === 'host_key_changed',
    probe: ['unreachable', 'auth_failed', 'handshake_refused', 'timeout'].includes(probe),
    identity: c.dial === 'cert_mismatch' || c.peer?.state === 'identity_changed',
  };
}

export const needsLook = (c: RosterComputer): boolean => Object.values(lookFlags(c)).some(Boolean);

export function inFilter(c: RosterComputer, key: FilterKey): boolean {
  if (key === 'all') return true;
  if (key === 'inpack') return c.kind === 'pack';
  if (key === 'overssh') return c.transport === 'ssh' && !c.isSelf;
  if (key === 'sshonly') return c.kind === 'ssh-only';
  if (key === 'older') return c.transport === 'ssh' && !c.isSelf && c.kind !== 'ssh-only';
  return lookFlags(c)[key];
}

export function countsOf(list: readonly RosterComputer[]): Record<FilterKey, number> {
  const n = {} as Record<FilterKey, number>;
  [...PACK_FILTERS, ...LOOK_FILTERS].forEach((k) => (n[k] = list.filter((c) => inFilter(c, k)).length));
  return n;
}

export function freeCpu(c: RosterComputer): number | null {
  const load = c.machine?.snapshot?.load;
  if (!load || load.load_1 == null || load.cores == null || ['unreachable', 'refused', 'local_network_blocked'].includes(c.dial)) return null;
  return Math.max(0, Math.round(load.cores - load.load_1));
}

export function haystack(c: RosterComputer): string {
  const h = c.host;
  const tools = Object.entries(c.machine?.snapshot?.toolchain ?? {}).filter(([, on]) => on).map(([k]) => k);
  return [c.name, c.machine?.specs?.model, c.entry?.fid_short, h?.ssh_target, h?.ssh_port, h?.socket, h?.machine_id, h?.login_shell, ...tools].filter((x) => x != null).join(' ').toLowerCase();
}

export const matches = (c: RosterComputer, q: string): boolean => q.trim() === '' || haystack(c).includes(q.trim().toLowerCase());

const ageMs = (at: string | null): number => (at ? Math.max(0, Date.now() - Date.parse(at)) : Number.POSITIVE_INFINITY);

export function sortRoster(list: readonly RosterComputer[], by: SortKey): RosterComputer[] {
  const score = (c: RosterComputer): number => (needsLook(c) ? 0 : c.isAlpha ? 1 : 2);
  const byName = (a: RosterComputer, b: RosterComputer): number => a.name.localeCompare(b.name);
  return [...list].sort((a, b) => {
    if (by === 'name') return byName(a, b);
    if (by === 'free') {
      const x = freeCpu(a), y = freeCpu(b);
      return x === null && y === null ? byName(a, b) : x === null ? 1 : y === null ? -1 : y - x;
    }
    if (by === 'seen') return ageMs(a.lastSeen) - ageMs(b.lastSeen) || byName(a, b);
    return score(a) - score(b) || byName(a, b);
  });
}

export const loginOf = (h: HostRow | null): string | null => (h?.ssh_target ? `${h.ssh_target}${h.ssh_port ? `:${h.ssh_port}` : ''}` : null);

export const sshCommand = (h: HostRow): string => `ssh ${h.ssh_port ? `-p ${h.ssh_port} ` : ''}${h.ssh_target ?? ''}`;

export function unlinkedNearby(found: readonly DiscoveredMac[], list: readonly RosterComputer[]): DiscoveredMac[] {
  const fids = new Set(list.flatMap((c) => [c.entry?.fid, c.peer?.fid].filter(Boolean)));
  return found.filter((d) => !fids.has(d.fid));
}

export const canLead = (c: RosterComputer): boolean => !c.isAlpha && !c.isSelf && c.kind !== 'ssh-only' && c.machine?.paired === true;

export type ReconnectSituation = 'main_now' | 'normal' | 'main_offline' | 'looking';

export const MAIN_OFFLINE_SECONDS = 300;

export function situationOf(view: PackMachinesView | null): ReconnectSituation {
  if (!view) return 'normal';
  const self = view.machines.find((m) => m.is_self);
  if (self?.is_master) return view.interim === true ? 'main_now' : 'normal';
  const main = view.machines.find((m) => m.is_master && !m.is_self);
  if (!self || !main || main.link_path === 'direct' || main.link_path === 'relay') return 'normal';
  return main.age_seconds !== null && main.age_seconds > MAIN_OFFLINE_SECONDS ? 'main_offline' : 'looking';
}

export function takeoverReasonKey(view: PackMachinesView | null): TakeoverReason | 'unknown' {
  return view?.takeover_available?.reason ?? 'unknown';
}

export const orderEditable = (view: PackMachinesView | null): boolean =>
  view?.machines.some((m) => m.is_self && m.is_master) === true && view.interim !== true;

export const successorOrder = (list: readonly RosterComputer[]): RosterComputer[] =>
  list.filter((c) => c.rank !== null).sort((a, b) => (a.rank as number) - (b.rank as number));

export function moveInOrder(ids: readonly string[], id: string, dir: -1 | 1): string[] {
  const at = ids.indexOf(id);
  const to = at + dir;
  if (at < 0 || to < 0 || to >= ids.length) return [...ids];
  const next = [...ids];
  [next[at], next[to]] = [next[to]!, next[at]!];
  return next;
}

export const strandedCount = (list: readonly RosterComputer[]): number => list.filter((c) => c.needsUpdate).length;
