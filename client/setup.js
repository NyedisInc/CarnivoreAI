
const STATE_URL = '/api/v1/setup/state';

const TOKEN_KEY = 'claude_tunnel_token';

function storedToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch (err) {
    return null;
  }
}

function headers(extra) {
  const out = Object.assign({ Accept: 'application/json' }, extra || {});
  const token = storedToken();
  if (token) out.Authorization = 'Bearer ' + token;
  return out;
}

function esc(value) {
  const div = document.createElement('div');
  div.textContent = value === undefined ? '' : String(value);
  return div.innerHTML;
}

function renderValue(value) {
  if (value === null || value === undefined) return '(not set)';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (err) {
    return String(value);
  }
}

function renderCheck(check) {
  let cls = 'unknown';
  let glyph = '?';
  if (check.passed === true) { cls = 'pass'; glyph = 'Y'; }
  else if (check.passed === false) { cls = 'fail'; glyph = 'N'; }
  return (
    '<div class="check" data-check="' + esc(check.key) + '" data-passed="' +
    (check.passed === null ? 'unknown' : String(check.passed)) + '">' +
    '<span class="mark ' + cls + '">' + glyph + '</span>' +
    '<span><strong>' + esc(check.title) + '</strong><br>' +
    '<span class="muted">' + esc(check.detail) + '</span></span></div>'
  );
}

function renderItem(item, index) {
  const name = 'decision-' + index;
  const takeNew = item.can_take_new_default
    ? '<label class="choice"><input type="radio" name="' + esc(name) +
      '" value="take_new" data-path="' + esc(item.path) + '">' +
      'Take the new default<span class="consequence">' +
      esc(item.if_you_take_the_new_default) + '</span></label>'
    : '';
  return (
    '<div class="card item" data-path="' + esc(item.path) + '" data-outcome="' +
    esc(item.outcome) + '">' +
    '<h3>' + esc(item.path) + '</h3>' +
    '<p><strong>' + esc(item.headline) + '</strong></p>' +
    '<p class="muted">' + esc(item.what_it_means) + '</p>' +
    '<div class="values">' +
    '<div class="value-box"><h4>Your value</h4><pre>' +
    esc(renderValue(item.yours)) + '</pre></div>' +
    '<div class="value-box"><h4>Shipped default</h4><pre>' +
    esc(renderValue(item.shipped_default)) + '</pre></div>' +
    '</div>' +
    '<div class="choices">' +
    '<label class="choice"><input type="radio" name="' + esc(name) +
    '" value="keep" data-path="' + esc(item.path) + '" checked>' +
    'Keep mine<span class="consequence">' + esc(item.if_you_keep_yours) +
    '</span></label>' + takeNew +
    '</div></div>'
  );
}

function renderExposure(exposure) {
  if (!exposure.effective_host) {
    return '<div class="banner" id="exposure-banner">' +
      'The address this server is listening on could not be determined. ' +
      'Your configured address is <code>' + esc(exposure.configured_host) +
      '</code>, which is what was requested and not proof of what is ' +
      'reachable. Restart the server from the menu bar to settle this.' +
      '</div>';
  }
  const cls = exposure.locked_down ? 'banner' : 'banner ok';
  let text = 'Listening on <code>' + esc(exposure.effective_host) + '</code>. ';
  if (exposure.locked_down) {
    text += 'Locked to this machine until setup finishes. Your configured ' +
      'address <code>' + esc(exposure.configured_host) +
      '</code> takes effect after setup completes and the server restarts.';
  } else {
    text += 'This is the address you configured.';
  }
  return '<div class="' + cls + '" id="exposure-banner">' + text + '</div>';
}

function renderLogin() {
  return (
    '<div class="banner" id="login-required">This instance is already set up, ' +
    'so the wizard is behind your authenticator.</div>' +
    '<div class="card"><h3>Enter your 6-digit code</h3>' +
    '<p class="muted">Same code you use to sign in to Carnivore.</p>' +
    '<input type="text" id="totp-code" inputmode="numeric" autocomplete="one-time-code" ' +
    'maxlength="6" placeholder="000000">' +
    '<div class="actions"><button id="login-btn">Unlock</button></div>' +
    '<p class="muted" id="login-error"></p></div>'
  );
}

async function submitLogin() {
  const field = document.getElementById('totp-code');
  const errorLine = document.getElementById('login-error');
  errorLine.textContent = '';
  try {
    const resp = await fetch('/api/v1/auth/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: (field.value || '').trim() })
    });
    const data = await resp.json().catch(function () { return {}; });
    if (!resp.ok) {
      errorLine.textContent = data.detail || ('Login failed (HTTP ' + resp.status + ').');
      return;
    }
    const token = data.access_token || data.token;
    if (!token) {
      errorLine.textContent = 'The server accepted the code but returned no token.';
      return;
    }
    window.localStorage.setItem(TOKEN_KEY, token);
    load();
  } catch (err) {
    errorLine.textContent = 'Could not reach the server: ' + err.message;
  }
}

function collectDecisions() {
  const picked = document.querySelectorAll('.choices input[type=radio]:checked');
  return Array.prototype.map.call(picked, function (input) {
    return { path: input.getAttribute('data-path'), choice: input.value };
  });
}

function isLocalOnly(status, data) {
  return status === 403 && !!data && !!data.detail && data.detail.reason === 'setup_local_only';
}

function failureText(status, data) {
  if (isLocalOnly(status, data)) {
    return 'setup can only be finished on the computer Carnivore runs on.';
  }
  return typeof data.detail === 'string' ? data.detail : 'HTTP ' + status;
}

async function applyDecisions() {
  const status = document.getElementById('apply-status');
  status.textContent = 'Applying...';
  try {
    const resp = await fetch('/api/v1/setup/apply', {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ decisions: collectDecisions() })
    });
    const data = await resp.json().catch(function () { return {}; });
    if (!resp.ok) {
      status.textContent = 'Failed: ' + failureText(resp.status, data);
      return;
    }
    status.textContent = data.changed && data.changed.length
      ? 'Updated ' + data.changed.join(', ') + '. Backup: ' + data.backup
      : 'Nothing needed changing.';
    load();
  } catch (err) {
    status.textContent = 'Could not reach the server: ' + err.message;
  }
}

function render(state) {
  const firstRun = state.mode === 'first_run';
  document.getElementById('wizard-title').textContent =
    firstRun ? 'Finish setting up Carnivore' : 'Review your configuration';
  document.getElementById('wizard-lede').textContent = firstRun
    ? 'This instance is not set up yet. Nothing outside this machine can reach it until it is.'
    : 'Your configuration against the defaults shipped with this version. Nothing changes until you choose it.';

  let html = renderExposure(state.exposure);

  html += '<h2>Setup checks</h2><div class="card" id="setup-checks">' +
    state.setup.checks.map(renderCheck).join('') + '</div>';

  const plan = state.plan || {};
  html += '<h2>Configuration</h2>';

  if (plan.unreadable) {
    html += '<div class="banner danger" id="plan-unreadable">' +
      esc(plan.unreadable) + '</div>';
  } else if (!plan.items || plan.items.length === 0) {
    html += '<div class="banner ok" id="plan-clean">Nothing needs a decision. ' +
      'Your configuration matches the shipped defaults everywhere it matters.</div>';
  } else {
    if (!plan.had_base) {
      html += '<div class="card"><p class="muted">No record of the previous ' +
        'defaults exists yet, so anything differing from a shipped default is ' +
        'reported as undeterminable rather than guessed at. Your value is kept ' +
        'in every case. This is noisy exactly once.</p></div>';
    }
    html += plan.items.map(renderItem).join('');
    html += '<div class="actions"><button id="apply-btn">Apply my choices</button>' +
      '<span class="muted" id="apply-status"></span></div>';
  }

  if (plan.adopting && plan.adopting.length) {
    html += '<h2>Arriving automatically</h2><div class="card"><p class="muted">' +
      'You never changed these, so the new defaults apply with no decision ' +
      'needed.</p><pre>' +
      esc(plan.adopting.map(function (a) { return a.path; }).join('\n')) +
      '</pre></div>';
  }

  if (firstRun) {
    html += '<h2>Finish</h2><div class="card" id="finish-pair"><p>Setup finishes ' +
      'when you pair an authenticator app. Open Carnivore on this computer to ' +
      'scan the code.</p><div class="actions"><button id="pair-btn">Pair an ' +
      'authenticator</button></div></div>';
  }

  document.getElementById('wizard-body').innerHTML = html;

  const applyBtn = document.getElementById('apply-btn');
  if (applyBtn) applyBtn.addEventListener('click', applyDecisions);
  const pairBtn = document.getElementById('pair-btn');
  if (pairBtn) pairBtn.addEventListener('click', function () { location.assign('/'); });
}

async function load() {
  const body = document.getElementById('wizard-body');
  try {
    const resp = await fetch(STATE_URL, { headers: headers() });
    if (resp.status === 401) {
      document.getElementById('wizard-title').textContent = 'Review your configuration';
      document.getElementById('wizard-lede').textContent =
        'This instance is set up, so the wizard needs your authenticator.';
      body.innerHTML = renderLogin();
      document.getElementById('login-btn').addEventListener('click', submitLogin);
      document.getElementById('totp-code').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') submitLogin();
      });
      return;
    }
    if (!resp.ok) {
      const data = await resp.json().catch(function () { return {}; });
      if (isLocalOnly(resp.status, data)) {
        document.getElementById('wizard-title').textContent = 'Finish setup on the computer';
        document.getElementById('wizard-lede').textContent = '';
        body.innerHTML = '<div class="banner danger" id="state-local-only">Setup can only be ' +
          'finished on the computer Carnivore runs on. Open Carnivore there.</div>';
        return;
      }
      body.innerHTML = '<div class="banner danger" id="state-error">The server ' +
        'answered HTTP ' + resp.status + ', so nothing about this instance could ' +
        'be determined. Nothing has been changed.</div>';
      return;
    }
    render(await resp.json());
  } catch (err) {
    body.innerHTML = '<div class="banner danger" id="state-error">Could not reach ' +
      'the server (' + esc(err.message) + '), so nothing about this instance could ' +
      'be determined.</div>';
  }
}

document.addEventListener('DOMContentLoaded', load);
