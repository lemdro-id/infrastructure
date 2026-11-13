FROM ghcr.io/rystaf/mlmym@sha256:aa6c284e739de6eb2d341aa0a6b59479b4dde61f3c85ac5fb1fc419d4f231b2e
USER root
# Anubis v1.28.2 linux-amd64 (https://github.com/TecharoHQ/anubis/releases/tag/v1.28.2)
# tarball sha256 from the GitHub release asset digest; verified 2026-11-12 for lemmy-ui.
ARG ANUBIS_VERSION=1.28.2
ARG ANUBIS_TARBALL_SHA256=69fa671d5438e4f54a50128228cf8c901611fea0ef5b25ad33f8514d8d24fe13
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx supervisor ca-certificates curl dnsutils \
 && curl -fsSL -o /tmp/anubis.tgz \
      "https://github.com/TecharoHQ/anubis/releases/download/v${ANUBIS_VERSION}/anubis-${ANUBIS_VERSION}-linux-amd64.tar.gz" \
 && echo "${ANUBIS_TARBALL_SHA256}  /tmp/anubis.tgz" | sha256sum -c - \
 && tar -xzf /tmp/anubis.tgz -C /tmp \
 && install -D -m 0755 /tmp/anubis-${ANUBIS_VERSION}-linux-amd64/bin/anubis /usr/local/bin/anubis \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/anubis.tgz /tmp/anubis-${ANUBIS_VERSION}-linux-amd64 \
 && useradd --system --no-create-home --home-dir /app --shell /usr/sbin/nologin mlmym \
 && chown -R mlmym:mlmym /app
COPY ./nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisord.conf
COPY start-nginx.sh mlmym-peers.sh mlmym-peers-loop.sh /usr/local/bin/
COPY anubis-botPolicies.yaml /etc/anubis/botPolicies.yaml
RUN chmod 0755 /usr/local/bin/start-nginx.sh /usr/local/bin/mlmym-peers.sh /usr/local/bin/mlmym-peers-loop.sh \
 && mkdir -p /var/log/supervisor
# Debian's supervisor package defaults to /etc/supervisor/supervisord.conf, so pass -c.
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
EXPOSE 8080
