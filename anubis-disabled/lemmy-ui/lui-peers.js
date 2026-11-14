// Writes an nginx map of this app's machine IDs (from Fly's internal DNS
// TXT record vms.<app>.internal) so nginx only fly-replays to machines that
// exist. Fly answers fly-replay to an unknown instance with HTTP 400, so a
// stale lui_machine cookie must never be replayed.
// usage: node lui-peers.js <outfile>
// exit 0 = file written (changed), 3 = unchanged, 1 = lookup failed (file untouched)
const fs = require("fs");
const dns = require("dns").promises;
const out = process.argv[2];
const app = process.env.FLY_APP_NAME || "";
const self = process.env.FLY_MACHINE_ID || "";
const render = (ids) =>
  "map $lui_cookie $lui_known {\n    default \"\";\n" +
  ids.map((id) => `    "${id}" "${id}";\n`).join("") + "}\n";
(async () => {
  if (!/^[a-z0-9-]+$/.test(app)) throw new Error("no FLY_APP_NAME");
  const r = new dns.Resolver({ timeout: 2000, tries: 2 });
  const txt = (await r.resolveTxt(`vms.${app}.internal`)).map((c) => c.join("")).join(",");
  const ids = new Set();
  for (const entry of txt.split(",")) {
    const id = entry.trim().split(/\s+/)[0];
    if (/^[0-9a-f]{1,32}$/.test(id)) ids.add(id);
  }
  if (/^[0-9a-f]{1,32}$/.test(self)) ids.add(self);
  const body = render([...ids].sort());
  let old = null;
  try { old = fs.readFileSync(out, "utf8"); } catch {}
  if (old === body) process.exit(3);
  fs.writeFileSync(out + ".tmp", body);
  fs.renameSync(out + ".tmp", out);
  process.exit(0);
})().catch((e) => { console.error("lui-peers: " + e.message); process.exit(1); });
