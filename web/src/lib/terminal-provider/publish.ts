import { TerminalProvider } from './provider';

export function publishTerminalProvider(): void {
  (window as unknown as { TerminalProvider?: typeof TerminalProvider }).TerminalProvider = TerminalProvider;
}
