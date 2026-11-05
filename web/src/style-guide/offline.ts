import { auth } from '../opscenter/api/auth.svelte';
import { seedSwarmSwitch } from '../lib/swarm-switch/control.svelte';

auth.state = 'signed-out';
auth.notice = '';

seedSwarmSwitch({ enabled: true });
