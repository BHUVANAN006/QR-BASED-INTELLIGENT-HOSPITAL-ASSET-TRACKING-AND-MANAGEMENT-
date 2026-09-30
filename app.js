
(() => {
  if (document.body.dataset.loggedIn !== "true") return;
  let lastEmergencyId = null;
  const banner = document.getElementById("liveEmergency");
  const badge = document.getElementById("messageBadge");

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.12, ctx.currentTime);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.45);
    } catch (_) {}
  }

  async function poll() {
    try {
      const res = await fetch("/api/updates", {headers: {"Accept": "application/json"}});
      if (!res.ok) return;
      const data = await res.json();
      if (data.unread_messages > 0) {
        badge.textContent = data.unread_messages;
        badge.classList.remove("hidden");
      } else badge.classList.add("hidden");

      if (data.emergencies.length) {
        const e = data.emergencies[0];
        banner.innerHTML = `🚨 ${e.emergency_type}: ${e.description} — ${e.location_code || e.department} · <a href="/emergency">Open alert</a>`;
        banner.classList.remove("hidden");
        if (lastEmergencyId !== e.id) {
          lastEmergencyId = e.id;
          beep();
          if (navigator.vibrate) navigator.vibrate([800,250,800,250,800]);
        }
      } else {
        banner.classList.add("hidden");
        lastEmergencyId = null;
      }
    } catch (_) {}
  }
  poll();
  setInterval(poll, 5000);
})();
