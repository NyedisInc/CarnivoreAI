export default {
    'cplug.publicboard.name': 'public review links',
    'cplug.publicboard.description': 'lets people outside your network open one review board through your own reverse proxy, look at it, and leave answers and comments, and nothing else. off by default. this version only opens the guarded door: it answers not found to everything until links exist.',
    'cplug.publicboard.settings.port': 'port',
    'cplug.publicboard.settings.port_help': 'the port the public door listens on, 1024 to 65535. never 5000 or 8000. your reverse proxy forwards to it.',
    'cplug.publicboard.settings.bind_address': 'bind address',
    'cplug.publicboard.settings.bind_address_help': 'the one network address of this computer that offers the door, for example the lan address your proxy reaches. never every address. 127.0.0.1 keeps it on this computer.',
    'cplug.publicboard.settings.hostnames': 'host names',
    'cplug.publicboard.settings.hostnames_help': 'the public names your proxy forwards, separated by commas, lowercase, no port. a request for any other name is refused. an address instead of a name is refused.',
    'cplug.publicboard.settings.trusted_proxies': 'trusted proxies',
    'cplug.publicboard.settings.trusted_proxies_help': 'the exact address of each reverse proxy allowed to reach the door, separated by commas. no ranges, no names, not this computer. every other computer that connects is refused. empty: the door stays closed.',
};
