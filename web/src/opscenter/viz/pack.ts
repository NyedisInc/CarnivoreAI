import type { AgentLoad, PackMachine, PackMachinesView } from '../../lib/pack-machines/pack-machines-store.svelte';

export interface PackBox {
  installId: string;
  label: string;
  isMaster: boolean;
  isSelf: boolean;
  state: string;
  live: boolean;
  cores: number | null;
  loadPct: number | null;
  barPct: number | null;
  linePct: number | null;
  level: 'in_use' | 'away' | null;
  reserveCpuPct: number | null;
  reserveMemPct: number | null;
  overLine: boolean;
  cpuPct: number | null;
  memPct: number | null;
  diskPct: number | null;
  battery: { percent: number | null; onBattery: boolean } | null;
  agentCount: number | null;
  agentCores: number | null;
  agentRssMb: number | null;
  throttled: number;
  more: number;
  agents: PackAgent[];
}

export interface PackAgent extends AgentLoad {
  machine: string;
  machineId: string;
}

export interface PackTotals {
  machines: number;
  reporting: number;
  silent: number;
  agents: number | null;
  agentCores: number | null;
  agentRssMb: number | null;
  cores: number | null;
}

export interface PackModel {
  boxes: PackBox[];
  agents: PackAgent[];
  totals: PackTotals;
}

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const clamp = (value: number): number => Math.min(100, Math.max(0, value));
const round1 = (value: number): number => Math.round(value * 10) / 10;

function box(machine: PackMachine): PackBox {
  const snap = machine.snapshot;
  const cores = num(snap?.load.cores ?? machine.specs?.cores);
  const load1 = num(snap?.load.load_1);
  const loadPct = snap && cores && load1 !== null ? round1((load1 / cores) * 100) : null;
  const reserve = snap?.reserve;
  const reserveCpu = num(reserve?.cpu_pct);
  const linePct = reserveCpu === null ? null : clamp(100 - reserveCpu);
  const section = snap?.agents ?? null;
  const machineCpu = num(section?.machine.cpu_pct);
  const battery = snap?.battery;
  const agents: PackAgent[] = (section?.rows ?? []).map((row) => ({ ...row, machine: machine.label, machineId: machine.install_id }));
  return {
    installId: machine.install_id,
    label: machine.label,
    isMaster: machine.is_master,
    isSelf: machine.is_self,
    state: machine.state,
    live: snap !== null,
    cores,
    loadPct,
    barPct: loadPct === null ? null : clamp(loadPct),
    linePct,
    level: reserve?.level ?? null,
    reserveCpuPct: reserveCpu,
    reserveMemPct: num(reserve?.mem_pct),
    overLine: loadPct !== null && linePct !== null && loadPct > linePct,
    cpuPct: cores && machineCpu !== null ? round1(machineCpu / cores) : null,
    memPct: num(snap?.load.memory_percent),
    diskPct: num(snap?.load.disk_percent),
    battery: battery && battery.present ? { percent: num(battery.percent), onBattery: battery.on_battery === true } : null,
    agentCount: section ? section.carnivore.agents : null,
    agentCores: section ? round1(section.carnivore.cpu_pct / 100) : null,
    agentRssMb: section ? Math.round(section.carnivore.rss_mb) : null,
    throttled: snap?.throttled ?? 0,
    more: section?.truncated ?? 0,
    agents,
  };
}

function sum(boxes: PackBox[], pick: (b: PackBox) => number | null): number | null {
  const values = boxes.map(pick).filter((v): v is number => v !== null);
  return values.length ? round1(values.reduce((a, b) => a + b, 0)) : null;
}

export function packModel(view: PackMachinesView | null): PackModel {
  const boxes = (view?.machines ?? []).filter((m) => m.paired).map(box);
  boxes.sort((a, b) => Number(b.isMaster) - Number(a.isMaster) || Number(b.isSelf) - Number(a.isSelf) || a.label.localeCompare(b.label));
  const live = boxes.filter((b) => b.live);
  const agents = live.flatMap((b) => b.agents).sort((a, b) => b.cpu_pct - a.cpu_pct);
  return {
    boxes,
    agents,
    totals: {
      machines: boxes.length,
      reporting: live.length,
      silent: boxes.length - live.length,
      agents: sum(live, (b) => b.agentCount),
      agentCores: sum(live, (b) => b.agentCores),
      agentRssMb: sum(live, (b) => b.agentRssMb),
      cores: sum(live, (b) => b.cores),
    },
  };
}
