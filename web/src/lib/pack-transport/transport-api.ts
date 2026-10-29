import { authFetch } from '../../opscenter/api/auth.svelte';

export interface TransportView {
  air_gap: boolean;
  account: string | null;
  source: string;
  needs_card: boolean;
  rung: string;
  rung_reason: string;
  logged_in: string[];
}

export interface PublishCard {
  name: string;
  private: true;
  owner: string | null;
  account: string | null;
  account_source: string;
  asks: string[];
  offered: boolean;
  reason: string | null;
}

export interface Published {
  url: string;
  owner: string;
  name: string;
  private: true;
}

export interface TransportApi {
  read(name: string): Promise<TransportView>;
  setAirGap(name: string, airGap: boolean): Promise<unknown>;
  setAccount(name: string, account: string | null): Promise<unknown>;
  card(name: string): Promise<PublishCard>;
  publish(name: string, answers: { owner?: string; account?: string }): Promise<Published>;
}

const seg = (value: string): string => encodeURIComponent(value);
const send = <T>(path: string, method: string, body?: unknown): Promise<T> =>
  authFetch<T>(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const transportApi: TransportApi = {
  read: (name) => send(`/projects/${seg(name)}/github-account`, 'GET'),
  setAirGap: (name, airGap) => send(`/projects/${seg(name)}/air-gap`, 'PUT', { air_gap: airGap }),
  setAccount: (name, account) => send(`/projects/${seg(name)}/github-account`, 'PUT', { account }),
  card: (name) => send(`/projects/${seg(name)}/publish-repo`, 'GET'),
  publish: (name, answers) => send(`/projects/${seg(name)}/publish-repo`, 'POST', answers),
};

export interface Replica {
  install_id: string;
  label: string;
  state: string;
}

export interface ReplicasView {
  pack_state: string;
  replicas: Replica[];
}

export interface ReplicasApi {
  list(name: string): Promise<ReplicasView>;
  add(name: string, machine: string): Promise<unknown>;
  remove(name: string, machine: string): Promise<unknown>;
}

export const replicasApi: ReplicasApi = {
  list: (name) => send(`/projects/${seg(name)}/replicas`, 'GET'),
  add: (name, machine) => send(`/projects/${seg(name)}/replicas`, 'POST', { machine }),
  remove: (name, machine) => send(`/projects/${seg(name)}/replicas/${seg(machine)}`, 'DELETE'),
};
