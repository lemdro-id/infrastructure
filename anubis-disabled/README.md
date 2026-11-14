# Anubis builds (disabled)

Since 2026-11-13, old.lemdro.id (mlmym) and l.lemdro.id (lemmy-ui) are protected by a
Cloudflare WAF custom rule instead of Anubis:

- zone `lemdro.id`, phase `http_request_firewall_custom`
- ruleset `cccad4590f3a43928dc978d038331ce9`, rule `a5bc50282eca4b08a1229a255214c201`
- action `managed_challenge`; expression `http.host in {...}` listing `old.lemdro.id` and
  `l.lemdro.id` bare, with a trailing dot, and with every Cloudflare-proxied port
  (80 443 8080 8880 2052 2082 2086 2095 2053 2083 2087 2096 8443), because the free
  plan has no regex and `http.host` includes the port.

These directories are the last Anubis deployments, kept unchanged. The
`ED25519_PRIVATE_KEY_HEX` secret is still set on both Fly apps, so re-enabling is one
command (run from the repo root):

```sh
# mlmym, Anubis 1.28.2 + sticky peers (was v16)
(cd anubis-disabled/mlmym && fly deploy -a lemdroid-mlmym \
  --image registry.fly.io/lemdroid-mlmym:deployment-01M7AXV9P0GSEMK1ZJTFNYYZVF)

# lemmy-ui 0.19.21, Anubis 1.28.2 + sticky fly-replay (was v82)
(cd anubis-disabled/lemmy-ui && fly deploy -a lemdroid-lemmy-ui \
  --image registry.fly.io/lemdroid-lemmy-ui:deployment-01M78Y0A1N5X98EX1DTFMTV4BH)
```

If those registry images are gone, drop `--image` to rebuild from the Dockerfile in
each directory. The fly.toml in each directory has the Anubis health checks
(`/nginx_alive_check`, `/mlmym_alive_check` / `/node_alive_check`); do not deploy the
plain images with it.

If the Cloudflare rule is removed, redeploy Anubis first or old./l. are open to the crawlers again.
