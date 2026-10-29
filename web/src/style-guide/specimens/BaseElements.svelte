<script lang="ts">
  const uid = $props.id();
  const id = (name: string): string => `sg-be-${uid}-${name}`;
</script>

<div class="sg-be" data-oc-base>
  <div class="sg-be__col">
    <h1>heading one</h1>
    <h2>heading two</h2>
    <h3>heading three</h3>
    <h4>heading four</h4>
    <p>body text with a <a href="#base-elements">plain link</a>, some <code>inline code</code>, a key <kbd>ctrl</kbd> and
      <small>small print</small>.</p>
    <hr />
    <table>
      <thead><tr><th>session</th><th>state</th><th>age</th></tr></thead>
      <tbody>
        <tr><td>design base</td><td>working</td><td>4m</td></tr>
        <tr><td>task manager</td><td>idle</td><td>2h</td></tr>
      </tbody>
    </table>
  </div>
  <div class="sg-be__col">
    <div class="sg-be__row">
      <button type="button">secondary</button>
      <button type="button" data-btn="confirm">confirm</button>
      <button type="button" data-btn="danger">remove</button>
      <button type="button" data-btn="quiet">quiet</button>
      <button type="button" disabled>disabled</button>
    </div>
    <div class="sg-be__row">
      <button type="button" data-btn="secondary" data-size="sm">secondary sm</button>
      <button type="button" data-btn="confirm" data-size="sm">confirm sm</button>
      <button type="button" data-btn="danger" data-size="sm">remove sm</button>
      <button type="button" data-btn="quiet" data-size="sm">quiet sm</button>
      <a href="#base-elements" data-btn="secondary" data-size="sm">a link as a button</a>
    </div>
    <div class="sg-be__field"><label for={id('name')}>a text field</label><input id={id('name')} type="text" placeholder="say it in your words" /></div>
    <div class="sg-be__field"><label for={id('pick')}>a select</label><select id={id('pick')}><option>keep it</option><option>replace it</option></select></div>
    <div class="sg-be__field"><label for={id('note')}>a textarea</label><textarea id={id('note')} rows="2" placeholder="a longer note"></textarea></div>
    <div class="sg-be__field"><label for={id('bad')}>an invalid field</label><input id={id('bad')} type="text" value="too long" aria-invalid="true" /></div>
    <div class="sg-be__field"><label for={id('off')}>a disabled field</label><input id={id('off')} type="text" value="read only" disabled /></div>
    <fieldset>
      <legend>a fieldset</legend>
      <div class="sg-be__row">
        <label><input type="checkbox" checked /> a checkbox</label>
        <label><input type="radio" name={id('r')} checked /> one</label>
        <label><input type="radio" name={id('r')} /> two</label>
      </div>
    </fieldset>
  </div>
</div>
