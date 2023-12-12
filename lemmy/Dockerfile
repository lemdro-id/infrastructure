# syntax=docker/dockerfile:1
FROM docker.io/golang:1.21
WORKDIR /src
COPY go.mod go.sum proxy.go ./
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/proxy ./proxy.go

FROM docker.io/dessalines/lemmy:0.18.5
COPY --from=0 /bin/proxy /bin/proxy
COPY config.hjson /config/config.hjson
USER root
#RUN apk update && apk add --no-cache bash
COPY supervisord.conf /etc/supervisord.conf

RUN apk update && apk add --no-cache supervisor
RUN mkdir -p /var/log/supervisor
#COPY run_wrapper.sh /bin/run_wrapper.sh
#CMD ["bash -c /bin/run_wrapper.sh"]
CMD ["/usr/bin/supervisord -c /etc/supervisord.conf"]
EXPOSE 8080
