(function () {
  var nonce = null;
  var live = false;
  function send(message) {
    message.nonce = nonce;
    parent.postMessage(message, '*');
  }
  function declare() {
    send({
      verb: 'ui.actions',
      id: 'a' + Date.now(),
      actions: [
        { id: 'refresh', label: 'refresh now' },
        { id: 'live', label: 'live updates', kind: 'switch', on: live },
      ],
    });
  }
  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (data.verb === 'init') {
      nonce = data.nonce;
      document.getElementById('line').textContent = 'drawn at role ' + data.role;
      declare();
    } else if (data.verb === 'action' && data.id === 'live') {
      live = data.on === true;
      declare();
    }
  });
})();
