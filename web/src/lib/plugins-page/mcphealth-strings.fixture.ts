export const MCPHEALTH_STRINGS: Record<string, string> = {
    'cplug.mcphealth.name': 'mcp health',
    'cplug.mcphealth.description': 'watches the mcp servers of every live claude code and codex session and puts a yellow ! on a session row when one is down or needs a login, with the reason in its tooltip. off by default: with it off nothing is measured and no ! shows.',
    'cplug.mcphealth.settings.warn_mode': 'which servers may raise the !',
    'cplug.mcphealth.settings.warn_mode_help': 'all: every server. allow: only the servers listed below. block: every server except the ones listed below.',
    'cplug.mcphealth.settings.warn_mode.option.all': 'all servers',
    'cplug.mcphealth.settings.warn_mode.option.allow': 'only the listed servers',
    'cplug.mcphealth.settings.warn_mode.option.block': 'all but the listed servers',
    'cplug.mcphealth.settings.servers': 'server names',
    'cplug.mcphealth.settings.servers_help': 'the mcp server names as your config names them, separated by commas. case does not matter. a server left out by this list never shows on the row and never notifies.',
    'cplug.mcphealth.settings.notify': 'send notifications',
    'cplug.mcphealth.settings.notify_help': 'one notification when a server that may raise the ! goes down in a session, and one when it comes back. never repeated while it stays down, and none in the first minute after carnivore starts.',
};
