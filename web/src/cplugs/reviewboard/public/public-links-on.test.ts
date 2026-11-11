import { afterEach, describe, expect, it } from 'vitest';
import { boardHeaderKeys, resetBoardHeaderKeys } from '../board-header-keys';
import { cplugEnablement } from '../../host/enablement.svelte';
import { registerBoardKeys } from './board-keys';
import { publicLinksOn } from './public-links-on';

afterEach(() => {
  cplugEnablement.read = false;
  cplugEnablement.enabled = {};
  cplugEnablement.settings = {};
  resetBoardHeaderKeys();
});

function server(enabled: boolean, settings: Record<string, unknown>): void {
  cplugEnablement.read = true;
  cplugEnablement.enabled = { reviewboard: enabled };
  cplugEnablement.settings = { reviewboard: settings };
}

describe('publicLinksOn', () => {
  it('is off before the server has answered', () => {
    expect(publicLinksOn()).toBe(false);
  });

  it('is off when the review board is on but the setting is false or absent', () => {
    server(true, { publicLinksEnabled: false });
    expect(publicLinksOn()).toBe(false);
    server(true, {});
    expect(publicLinksOn()).toBe(false);
  });

  it('is off when the setting is true but the review board is off', () => {
    server(false, { publicLinksEnabled: true });
    expect(publicLinksOn()).toBe(false);
  });

  it('is on only for the review board on with the setting exactly true', () => {
    server(true, { publicLinksEnabled: true });
    expect(publicLinksOn()).toBe(true);
    server(true, { publicLinksEnabled: 'yes' });
    expect(publicLinksOn()).toBe(false);
  });

  it('draws no board header key while off and both the moment it is switched on', () => {
    registerBoardKeys();
    server(true, { publicLinksEnabled: false });
    expect(boardHeaderKeys()).toEqual([]);
    server(true, { publicLinksEnabled: true });
    expect(boardHeaderKeys().map((k) => k.id)).toEqual(['reviewboard.share', 'reviewboard.visitors']);
  });
});
