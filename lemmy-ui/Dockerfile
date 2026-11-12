FROM dessalines/lemmy-ui:0.19.21@sha256:d78d073a888c780f83e10850867841eca03261c8c459b65465fa337b4071768d
USER root
# Anubis v1.28.2 linux-amd64 (https://github.com/TecharoHQ/anubis/releases/tag/v1.28.2)
# tarball sha256 from the GitHub release asset digest; verified 2026-11-12.
ARG ANUBIS_VERSION=1.28.2
ARG ANUBIS_TARBALL_SHA256=69fa671d5438e4f54a50128228cf8c901611fea0ef5b25ad33f8514d8d24fe13
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx supervisor ca-certificates curl \
 && curl -fsSL -o /tmp/anubis.tgz \
      "https://github.com/TecharoHQ/anubis/releases/download/v${ANUBIS_VERSION}/anubis-${ANUBIS_VERSION}-linux-amd64.tar.gz" \
 && echo "${ANUBIS_TARBALL_SHA256}  /tmp/anubis.tgz" | sha256sum -c - \
 && tar -xzf /tmp/anubis.tgz -C /tmp \
 && install -D -m 0755 /tmp/anubis-${ANUBIS_VERSION}-linux-amd64/bin/anubis /usr/local/bin/anubis \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/anubis.tgz /tmp/anubis-${ANUBIS_VERSION}-linux-amd64
COPY ./nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisord.conf
COPY start-nginx.sh /usr/local/bin/start-nginx.sh
COPY anubis-botPolicies.yaml /etc/anubis/botPolicies.yaml
RUN mkdir -p /var/log/supervisor
# Debian's supervisor package defaults to /etc/supervisor/supervisord.conf, so pass -c.
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
EXPOSE 8080
