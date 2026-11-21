import { afterEach, describe, expect, test, vi } from 'vitest';
import {
  openSwarmAgentTerminal, registerSwarmAgentActions, renameSwarmAgent, SwarmActionsUnavailableError,
  turnOffSwarmAgent, unregisterSwarmAgentActions, wakeSwarmAgent,
} from './swarm-agent-actions';

afterEach(() => unregisterSwarmAgentActions());

describe('with no plugin registered', () => {
  test('every route action rejects with the unavailable error, and the terminal opener answers false', async () => {
    await expect(wakeSwarmAgent(1, 'resume')).rejects.toBeInstanceOf(SwarmActionsUnavailableError);
    await expect(renameSwarmAgent(1, 'x')).rejects.toBeInstanceOf(SwarmActionsUnavailableError);
    await expect(turnOffSwarmAgent(1, 'x')).rejects.toBeInstanceOf(SwarmActionsUnavailableError);
    await expect(openSwarmAgentTerminal(1)).resolves.toBe(false);
  });
});

describe('with the plugin registered', () => {
  test('each call reaches the plugin with its arguments', async () => {
    const actions = { wake: vi.fn(async () => {}), rename: vi.fn(async () => {}), turnOff: vi.fn(async () => {}), openTerminal: vi.fn(async () => true) };
    registerSwarmAgentActions(actions);
    await wakeSwarmAgent(3, 'resume');
    await renameSwarmAgent(3, 'New');
    await turnOffSwarmAgent(3, 'New');
    await expect(openSwarmAgentTerminal(3)).resolves.toBe(true);
    expect(actions.wake).toHaveBeenCalledWith(3, 'resume');
    expect(actions.rename).toHaveBeenCalledWith(3, 'New');
    expect(actions.turnOff).toHaveBeenCalledWith(3, 'New');
    expect(actions.openTerminal).toHaveBeenCalledWith(3);
  });

  test('after unregister the actions fail closed again, and unregistering twice is harmless', async () => {
    registerSwarmAgentActions({ wake: async () => {}, rename: async () => {}, turnOff: async () => {}, openTerminal: async () => true });
    unregisterSwarmAgentActions();
    unregisterSwarmAgentActions();
    await expect(wakeSwarmAgent(1, 'fresh')).rejects.toBeInstanceOf(SwarmActionsUnavailableError);
    await expect(openSwarmAgentTerminal(1)).resolves.toBe(false);
  });
});
