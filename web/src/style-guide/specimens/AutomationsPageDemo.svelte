<script lang="ts">
  import AutomationsScreen from '../../lib/automations/AutomationsScreen.svelte';
  import { data } from '../../lib/automations/page-store.svelte';
  import { scheduled } from '../../lib/automations/scheduled-store.svelte';
  import { feed, reports } from '../../lib/automations/feed-store.svelte';
  import { fixtureAutomations, fixtureCounts, fixtureFeed, fixtureProjects, fixtureSchedules, fixtureSessions, fixtureTargets } from './automations-fixture';

  data.fixture = true;
  data.automations = fixtureAutomations();
  data.counts = fixtureCounts();
  data.targets = fixtureTargets();
  data.projects = fixtureProjects;
  data.sessions = fixtureSessions;
  data.sessionsWanted = true;
  data.tab = 'automations';
  data.status = 'ready';
  data.selectedId = 'aut_scrooge';
  data.paneOpen = true;
  scheduled.rows = fixtureSchedules();
  feed.runs = fixtureFeed();
  feed.total = feed.runs.length;
  feed.status = 'ready';
  for (const run of feed.runs) reports[run.run_id] = { state: 'ready', report: run.report ?? null };
</script>


<div class="sg-automations-demo" style="display: grid; zoom: 0.75; width: 92rem; height: 70rem; overflow: hidden"><AutomationsScreen embedded={true} /></div>
