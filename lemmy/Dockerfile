# syntax=docker/dockerfile:1
FROM docker.io/golang:1.21
WORKDIR /src
COPY go.mod go.sum proxy.go ./
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/proxy ./proxy.go

FROM docker.io/dessalines/lemmy:0.19.3
COPY --from=0 /bin/proxy /bin/proxy
COPY config.hjson /config/config.hjson
COPY update_instance_timeout.sh /update_instance_timeout.sh
USER root
#RUN apk update && apk add --no-cache bash
COPY supervisord.conf /etc/supervisord.conf

RUN apt update && apt install -y supervisor postgresql-client-15
RUN mkdir -p /var/log/supervisor
ENTRYPOINT ["/usr/bin/supervisord"]
EXPOSE 8080
