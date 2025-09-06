FROM dessalines/lemmy-ui:0.19.11
USER root
RUN apk update && apk add --no-cache nginx supervisor
COPY ./nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisord.conf
RUN mkdir -p /var/log/supervisor
CMD ["/usr/bin/supervisord"]
EXPOSE 8080
