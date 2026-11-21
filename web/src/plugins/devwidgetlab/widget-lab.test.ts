import { describe, expect, it } from 'vitest';
import { harnessWidgets } from '../../widget-harness/catalog';
import { LAB_HOSTS, labWidgets, parseScenario } from '../sdk/widget-lab';

describe('labWidgets', () => {
  const widgets = labWidgets();
  const notes = widgets.find((one) => one.key === 'core.notes')!;

  it('lists exactly the widgets the harness draws, no second list', () => {
    expect(widgets.map((one) => one.key)).toEqual(harnessWidgets().map((one) => one.key));
    expect(widgets.length).toBeGreaterThan(20);
  });

  it('gives every widget every host, in page order', () => {
    for (const one of widgets) expect(one.hosts.map((host) => host.zone)).toEqual([...LAB_HOSTS]);
  });

  it('places notes on the two grids, the drawer and the pop-out, with its published sizes and a floor', () => {
    const [home, terminal, drawer, popout] = notes.hosts;
    expect([home, terminal, drawer, popout].every((host) => host!.supported)).toBe(true);
    const names = home!.sizes.map((size) => size.name);
    expect(names).toEqual(expect.arrayContaining(['s', 'm', 'l', 'phone']));
    expect(home!.sizes.find((size) => size.floor)?.name).toBe('s');
    expect(popout!.sizes).toEqual(home!.sizes);
    expect(drawer!.sizes.some((size) => size.h === null)).toBe(true);
  });

  it('marks a host the declaration does not place the widget in, with the reason, and draws nothing there', () => {
    const homeOnly = widgets.find((one) => one.hosts.some((host) => !host.supported));
    expect(homeOnly).toBeDefined();
    const refused = homeOnly!.hosts.find((host) => !host.supported)!;
    expect(refused.refusal).not.toBeNull();
  });
});

describe('the scenario check is the harness one', () => {
  it('is re-exported, parse only', () => {
    expect(parseScenario('{"GET /x": 1}').ok).toBe(true);
    expect(parseScenario('nope').ok).toBe(false);
  });
});
