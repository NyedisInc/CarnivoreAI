/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { setLocale } from '../i18n/index.svelte';
import { buildRoster, type RosterComputer } from './roster-model';
import RosterCard from './RosterCard.svelte';

setLocale('en');
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: id === 'alpha', paired: id === 'alpha',
  state: id === 'me' ? 'self' : 'connected', capabilities: [], specs: null, snapshot: null, roster_v1: null, ...over });
const link = (state: string) => ({ install_id: 'm3', state, since: 1700000000, dialed_by: 'this', standing: true, on_demand: false });
const host = { key: 'box', label: 'box', local: false, ssh_target: 'alice@box', ssh_port: null, computer_install_id: null, probed_at: null, socket: 'cloude' };

function roster(o: { linkState: string | null; alpha?: string; m3State?: string }): RosterComputer[] {
  return buildRoster({
    view: { self: { install_id: 'me' }, computers: [{ install_id: 'alpha', label: 'alpha', transport: 'tls', state: 'connected', last_link_at: null, dial: { state: 'linked' } }],
      ...(o.linkState ? { mesh: { switch: 'on', links: [link(o.linkState)] }, heard: { m3: { age_s: 4, at_ms: Date.now(), via: 'direct', app_version: '1.17.0' } } } : {}) } as never,
    machines: [machine('me'), machine('alpha', { state: o.alpha ?? 'connected' }), machine('m3', { state: o.m3State ?? 'reported_connected' })] as never, hosts: [host] as never, peers: [],
  });
}

let mounted: ReturnType<typeof mount>[] = [];
afterEach(() => { mounted.forEach((m) => unmount(m)); mounted = []; document.body.innerHTML = ''; });
function mark(list: RosterComputer[], id: string): { word: string; shape: string | null; tone: string | null; dial: string | null } {
  const target = document.createElement('ul');
  document.body.append(target);
  mounted.push(mount(RosterCard, { target, props: { c: list.find((c) => c.id === id)!, onOpen: () => {}, nowMs: Date.now() } }));
  flushSync();
  const st = target.querySelector('.pp-st')!;
  return { word: st.querySelector('.pp-st__word')!.textContent ?? '', shape: st.getAttribute('data-shape'), tone: st.getAttribute('data-tone'), dial: st.getAttribute('data-dial') };
}

describe('another member, the alpha up and reporting it connected', () => {
  test.each([
    ['unreachable', 'connected to alpha, unreachable'],
    ['not_held', 'connected to alpha, links when needed'],
    ['dialing', 'connected to alpha, dialing'],
  ])('direct link %s: the word names both, the mark is hollow ok, data-dial keeps the raw key', (state, word) => {
    expect(mark(roster({ linkState: state }), 'm3')).toEqual({ word, shape: 'hollow', tone: 'ok', dial: state });
  });
  test('direct link linked: one rule, filled ok', () => {
    expect(mark(roster({ linkState: 'linked' }), 'm3')).toEqual({ word: 'connected to alpha, linked', shape: 'filled', tone: 'ok', dial: 'linked' });
  });
  test.each([['cert_mismatch', 'tri', 'warn'], ['refused', 'slash', 'bad'], ['local_network_blocked', 'slash', 'bad'], ['excluded', 'slash', 'warn'], ['held_over', 'hollow', 'warn']])(
    'a fault on the direct path (%s) keeps its own look', (state, shape, tone) => {
      expect(mark(roster({ linkState: state }), 'm3')).toMatchObject({ shape, tone, dial: state });
    });
  test('mesh off: the word says connected to alpha and the mark is hollow ok, not the never dot', () => {
    expect(mark(roster({ linkState: null }), 'm3')).toEqual({ word: 'connected to alpha', shape: 'hollow', tone: 'ok', dial: 'never' });
  });
});

describe('another member, the alpha not vouching for it', () => {
  test('the alpha down, link unreachable: the link word and its own look, never ok', () => {
    expect(mark(roster({ linkState: 'unreachable', alpha: 'disconnected' }), 'm3')).toEqual({ word: 'unreachable', shape: 'slash', tone: 'bad', dial: 'unreachable' });
  });
  test('the alpha up but reporting it disconnected, link unreachable: the link look stays', () => {
    expect(mark(roster({ linkState: 'unreachable', m3State: 'reported_disconnected' }), 'm3')).toMatchObject({ word: 'unreachable', shape: 'slash', tone: 'bad' });
  });
  test('the alpha down, mesh off: unknown on the never dot', () => {
    expect(mark(roster({ linkState: null, alpha: 'disconnected' }), 'm3')).toEqual({ word: 'unknown', shape: 'dot', tone: 'dim', dial: 'never' });
  });
});

describe('the cards that keep today\'s word and mark', () => {
  test('this computer, the alpha as a paired computer and an ssh-only host', () => {
    const list = roster({ linkState: 'unreachable' });
    expect(mark(list, 'me')).toMatchObject({ shape: 'filled', tone: 'ok', dial: 'self' });
    expect(mark(list, 'alpha')).toEqual({ word: 'linked', shape: 'filled', tone: 'ok', dial: 'linked' });
    expect(mark(list, 'host:box')).toMatchObject({ shape: 'dot', tone: 'dim', dial: 'ssh' });
  });
  test('a star-paired member on the alpha\'s own page (member false) reads its own link', () => {
    const list = buildRoster({
      view: { self: { install_id: 'me' }, computers: [{ install_id: 'm3', label: 'm3', transport: 'tls', state: 'connected', last_link_at: null, dial: { state: 'unreachable' } }] } as never,
      machines: [machine('me', { is_master: true }), machine('m3', { state: 'reported_connected', paired: true })] as never, hosts: [], peers: [],
    });
    expect(list.find((c) => c.id === 'm3')!.member).toBe(false);
    expect(mark(list, 'm3')).toEqual({ word: 'unreachable', shape: 'slash', tone: 'bad', dial: 'unreachable' });
  });
});
