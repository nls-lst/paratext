// The project in the address, so a link can send someone straight to it (PTX-79).
//
//   /verify/?project=issa#/review           the project's current round
//   /verify/?project=monographs&round=2      an earlier round (read-only, as ever)
//   /verify/?project=issa#/review/<id>       one record
//
// The link names the project, not the round, so it still works after a new
// round is packaged. Kept free of the DOM so it can be tested on its own.

// Which dataset an address asks for: { name } when it resolves, { unknown }
// when it names something that isn't being served, {} when it names nothing.
export function datasetFromSearch(datasets, search) {
  const q = new URLSearchParams(search);
  const project = q.get("project");
  if (!project) return {};
  const rounds = datasets.filter((d) => d.base === project);
  if (!rounds.length) return { unknown: project };
  const want = q.get("round");
  if (want === null || want === "") {
    return { name: rounds.reduce((a, b) => (b.round > a.round ? b : a)).name };
  }
  const d = rounds.find((d) => String(d.round) === want);
  return d ? { name: d.name } : { unknown: `${project} round ${want}` };
}

// The query string for a dataset, keeping any other parameters as they are.
// The round is written only when it isn't the project's newest, so that the
// everyday link stays short and keeps following the current round.
export function searchForDataset(datasets, name, search) {
  const q = new URLSearchParams(search);
  q.delete("project");
  q.delete("round");
  const d = datasets.find((d) => d.name === name);
  if (d) {
    q.set("project", d.base);
    const newest = Math.max(...datasets.filter((x) => x.base === d.base).map((x) => x.round));
    if (d.round !== newest) q.set("round", String(d.round));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
