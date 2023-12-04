# syntax=docker/dockerfile:1
FROM golang:1.21
WORKDIR /src
COPY go.mod go.sum proxy.go ./
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/proxy ./proxy.go

FROM dessalines/lemmy:0.18.5
COPY --from=0 /bin/proxy /bin/proxy
RUN apt-get update && apt-get install -y supervisor
RUN mkdir -p /var/log/supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
CMD ["usr/bin/supervisord"]
