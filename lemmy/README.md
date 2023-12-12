# Config

The following environment variables are set as secrets in fly.io:

```
LEMMY_SMTP_PASSWORD
LEMMY_DATABASE_URL
```

Additionally, the pictrs API token needs to be set properly as well in `config.hjson`

# Integrated Load Shedding Reverse Proxy

Contained in this folder is `proxy.go`. This is designed to mitigate a common problem in running lemmy as a distributed
application, where particular web service requests may cause extremely high CPU usage for extended periods or take a
long time for other reasons. If not effectively managed, such requests slow down the processing of existing requests and
create inconsistencies in response times that affect user experience. Luckily, with fly.io, it is easy to perform
[dynamic request routing](https://fly.io/docs/reference/dynamic-request-routing/). The goal is to enhance the
consistency and reliability of this service by dynamically routing requests to less burdened instances.

## Request Routing and Replay Logic

Requests are received by the reverse proxy and selectively forwarded to a target service based on current load. When the
server detects that the average response time exceeds a certain threshold (`maxResponseTimeTarget`), it enters a load
shedding mode. The proxy starts dropping requests by reducing the `sampleFraction` - the fraction of requests that pass
through to the service.

The critical part of this system is the addition of a special header (`fly-replay`) to the responses or within the error
handling logic when the server is under high load. When a request is dropped due to load shedding, the header's value is
set to `replayHeaderValue`, which suggests the load balancer or cooperating service should replay this request to
another instance. Here's how it works:

1. **Non-idempotent requests and replaying**: In its current form, the server does not distinguish between idempotent
   and non-idempotent HTTP methods. If the replay logic is used unconditionally, it may replay non-idempotent requests (
   like POST, PUT, DELETE), which could lead to unintended side effects. The design should ideally handle this with a
   more cautious approach, or the downstream service should support idempotent key patterns.

2. **Replayed request detection**: Requests that have been replayed arrive with the `replayHeaderKey` header already
   set. The server distinguishes these replayed requests and treats them differently. If a request is marked as
   replayed (by containing the `replaySrcHeaderKey` header), it bypasses the load shedding logic, ensuring that the
   replay has a chance to complete without being subjected to further shedding.

## Health Check Endpoint

The health check endpoint provides a mechanism to determine the server's health. When the `sampleFraction` falls
below `minSampleFraction`, the health check endpoint will begin to return `http.StatusServiceUnavailable`, signaling
that the proxy is in a degraded state.

## Reverse Proxy & Error Handling

Within the `setupReverseProxy` function, additional behaviors are implemented:

- The `ModifyResponse` function sets a replay header on responses with a status code of 500s (indicating server errors)
  or 400s (indicating bad requests).
- The `ErrorHandler` function includes logic to set a replay header and return a 503 Service Unavailable if there is an
  issue proxying the request.

**Note**: The replay logic in `ErrorHandler` only activates if the request has not been replayed. Requests that have
already been replayed and then encounter an error will not have the header appended a second time, preventing potential
infinite replay loops.

## Goroutines for Statistics and Adjustment

Two goroutines run in the background:

1. The first routine prints statistics, such as the average response time and current sample fraction, to the logs every
   5 seconds.
2. The second routine adjusts the `sampleFraction` every 500 milliseconds based on the latest average response time.

**Recovery Logic**: An interesting point is the logic within the first goroutine, which checks if the `sampleFraction`
is below 1.0 (i.e., not all requests are being processed) and the time since the last response is more than 5 seconds.
If so, it assumes the server might be erroneously stuck in a high-load state due to receiving no requests and resets
`sampleFraction` to 50% and `emaResponseTime` to zero to allow for recovery.

## Advanced Considerations

- **Request Prioritization**: Currently, there is no prioritization mechanism; requests are shed uniformly. However,
  depending on the use case, it might be desirable to prioritize certain requests over others.
- **Sample Size and Min Sample Fraction**: These values are currently constants but could be made configurable at
  runtime or adaptive based on observed conditions.

## Limitations
- **Idempotency**: The lack of idempotency checks can trigger duplicated side-effects in certain API operations upon
  request replay.