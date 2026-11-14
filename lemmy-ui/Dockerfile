FROM dessalines/lemmy-ui:0.19.21@sha256:d78d073a888c780f83e10850867841eca03261c8c459b65465fa337b4071768d
USER root
RUN apt-get update && apt-get install -y --no-install-recommends nginx supervisor && rm -rf /var/lib/apt/lists/*
COPY ./nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisord.conf
RUN mkdir -p /var/log/supervisor
# Debian's supervisor package defaults to /etc/supervisor/supervisord.conf, so pass -c.
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
EXPOSE 8080
