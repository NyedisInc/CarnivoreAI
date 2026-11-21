export default {
    'cplug.timemachine.name': 'time machine check',
    'cplug.timemachine.description': 'checks every 15 minutes that time machine made a backup in the last 24 hours, and raises one alert when it did not or cannot tell',
    'cplug.timemachine.action.check_access': 'check access',
    'cplug.timemachine.alert.stale.title': 'time machine has not backed up lately',
    'cplug.timemachine.alert.stale.detail': 'the newest time machine backup is {hours} hours old (limit {max_hours}).',
    'cplug.timemachine.alert.unknown.title': 'cannot tell if time machine is backing up',
    'cplug.timemachine.alert.unknown.detail.access': 'macos refused carnivore permission to read time machine (full disk access is off). until you grant it, nobody can tell whether backups are running.',
    'cplug.timemachine.alert.unknown.detail.unreadable': 'carnivore could not read time machine, either because it has no access or because no backup disk answered. this is not a sign that it is fine.',
    'cplug.timemachine.alert.unknown.explain.access': 'macos blocks the time machine tool (tmutil) for any app that does not have full disk access. open privacy settings, switch on carnivore under full disk access, then press re-check now. you may need to restart carnivore once after switching it on.',
    'cplug.timemachine.alert.unknown.explain.unreadable': 'two things block this read. the most likely: carnivore lacks full disk access for the time machine tool (tmutil), so open privacy settings and switch carnivore on. the other: the backup disk is unplugged or asleep, so plug it in. then press re-check now.',
};
