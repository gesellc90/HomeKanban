// HomeKanban — die einzige eigene JavaScript-Datei. Lokal ausgeliefert, kein Build-Schritt,
// keine Abhängigkeit (CLAUDE.md §4). Die App bleibt ohne JavaScript vollständig bedienbar:
// jede Aktion ist ein echtes <form method="post">, HTMX liegt nur darüber.
//
// Warum es diese Datei überhaupt gibt: HTMX tauscht standardmäßig nur bei 2xx-Antworten.
// Fehlbedienung auf der Einkaufsliste — bereits abgehakte Position, unsinnige Menge — antwortet
// aber bewusst mit 409 oder 422 statt mit einem geschönten 200 (docs/PLAN.md §6, M4). Ohne den
// folgenden Handler würde die Antwort verworfen und der Nutzer bekäme gar keine Rückmeldung.
document.body.addEventListener("htmx:beforeSwap", function (event) {
  var status = event.detail.xhr.status;
  if (status === 409 || status === 422) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});
