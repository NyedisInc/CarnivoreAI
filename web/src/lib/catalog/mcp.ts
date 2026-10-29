import { boundedList } from './bounds';
import type { InstallPreview, McpServer } from './types';

export const MAX_MCP_SERVERS = 16;

export function mcpServers(preview: InstallPreview | null | undefined): McpServer[] {
    const listed = preview && Array.isArray(preview.mcp_servers) ? preview.mcp_servers : [];
    const ok = listed.filter((row) => row && typeof row.command === 'string' && row.command !== '');
    return boundedList(ok, MAX_MCP_SERVERS).shown;
}

function shown(arg: string): string {
    return /^[A-Za-z0-9_@%+=:,./-]+$/.test(arg) ? arg : `'${arg.replace(/'/g, "'\\''")}'`;
}

export function mcpCommandLine(server: McpServer): string {
    const args = Array.isArray(server.args) ? server.args.filter((a) => typeof a === 'string') : [];
    return [server.command, ...args].map(shown).join(' ');
}
