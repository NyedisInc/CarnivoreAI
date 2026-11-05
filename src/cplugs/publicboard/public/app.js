(function () {
  "use strict";
  var status = document.getElementById("status");
  var token = decodeURIComponent(location.hash.slice(1));
  var MESSAGES = {
    ended: "this link has ended",
    invalid: "this link is not valid",
    limited: "too many requests, try again in a minute",
    misrouted: "this page is not reachable right now: the server in front of it is not set up correctly. tell the person who sent you the link",
    unavailable: "this board cannot be reached right now"
  };
  function say(text) { status.textContent = text; }
  if (!token) { say("this link is not valid"); return; }
  fetch("/api/board", { headers: { "Carnivore-Board-Link": token }, cache: "no-store", credentials: "omit" })
    .then(function (res) { return res.json().then(function (body) { return { ok: res.ok, body: body }; }); })
    .then(function (res) {
      if (!res.ok) { say(MESSAGES[res.body.state] || MESSAGES.invalid); return; }
      var board = document.getElementById("board");
      board.textContent = "";
      var title = document.createElement("h1");
      title.textContent = res.body.title;
      var summary = document.createElement("p");
      summary.textContent = res.body.summary;
      var frame = document.createElement("iframe");
      frame.setAttribute("sandbox", "allow-scripts");
      frame.src = res.body.views[0].frame;
      board.append(title, summary, frame);
    })
    .catch(function () { say("this board cannot be reached right now"); });
})();
