# syntax=docker/dockerfile:1
FROM golang:1.21
WORKDIR /src
COPY go.mod go.sum proxy.go ./
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/proxy ./proxy.go

FROM dessalines/lemmy:0.18.5
COPY --from=0 /bin/proxy /bin/proxy
USER root
#RUN apk update && apk add --no-cache bash
RUN apk update && apk add --no-cache supervisor
RUN mkdir -p /var/log/supervisor
COPY run_wrapper.sh /bin/run_wrapper.sh
#CMD ["bash -c /bin/run_wrapper.sh"]
CMD ["/usr/bin/supervisord"]
EXPOSE 80