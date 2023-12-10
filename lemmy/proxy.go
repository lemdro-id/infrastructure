package main

import (
	"context"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sync"
	"time"
)

const (
	target             = "http://127.0.0.1:8536"
	listenAddr         = ":8080"
	responseTimeTarget = 500 * time.Millisecond
	sampleSize         = 500
	minSampleFraction  = 0.10 // Always allow at least 1% of requests through
	replayHeaderKey    = "fly-replay"
	replayHeaderValue  = "elsewhere=true"
	replaySrcHeaderKey = "fly-replay-src"
)

var (
	mutex               sync.Mutex
	times               = make([]time.Duration, 0, sampleSize)
	avgResponseTime     = time.Duration(0)
	sampleFraction      = 1.0 // percentage of requests to allow
	currentRequestCount = 0
	lastRequestTime     = time.Now()
)

func recordResponseTime(d time.Duration) {
	mutex.Lock()
	defer mutex.Unlock()

	lastRequestTime = time.Now()

	times = append(times, d)
	if len(times) > sampleSize {
		times = times[1:]
	}

	var total time.Duration
	for _, t := range times {
		total += t
	}

	if len(times) > 0 {
		avgResponseTime = total / time.Duration(len(times))
	} else {
		avgResponseTime = 0
	}

	if avgResponseTime > responseTimeTarget {
		// response time too high, shed some load
		sampleFraction = max(minSampleFraction, sampleFraction-0.001)
	} else {
		// response time low enough, gradually add load
		sampleFraction = min(1.0, sampleFraction+0.001)
	}
}

func shouldProcessRequest() bool {
	mutex.Lock()
	defer mutex.Unlock()

	// skip load checking if we are accepting all requests
	if sampleFraction == 1.0 {
		return true
	}

	allowedRequestCount := int(sampleFraction * float64(sampleSize))

	currentRequestCount++
	if currentRequestCount >= sampleSize {
		currentRequestCount = 0
		return false
	}

	return currentRequestCount <= allowedRequestCount
}

// setupReverseProxy function now returns the configured reverse proxy
func setupReverseProxy(target string) *httputil.ReverseProxy {
	targetURL, err := url.Parse(target)
	if err != nil {
		log.Fatalf("Invalid target URL: %v", err)
	}

	proxy := httputil.NewSingleHostReverseProxy(targetURL)

	proxy.ModifyResponse = func(response *http.Response) error {
		recordResponseTime(time.Since(response.Request.Context().Value("startTime").(time.Time)))

		originatedByReplay := response.Request.Header.Get(replaySrcHeaderKey) != ""
		if response.StatusCode >= http.StatusInternalServerError && !originatedByReplay {
			response.Header.Set(replayHeaderKey, replayHeaderValue)
		}

		return nil
	}

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, e error) {
		log.Printf("HTTP proxy error: %v", e)

		originatedByReplay := r.Header.Get(replaySrcHeaderKey) != ""
		if !originatedByReplay {
			w.Header().Set(replayHeaderKey, replayHeaderValue)
			http.Error(w, e.Error(), http.StatusServiceUnavailable)
		}
	}

	return proxy
}

// Function that configures the reverse proxy handler
func newReverseProxyHandler(proxy *httputil.ReverseProxy) func(http.ResponseWriter, *http.Request) {
	return func(res http.ResponseWriter, req *http.Request) {
		originatedByReplay := req.Header.Get(replaySrcHeaderKey) != ""

		if !shouldProcessRequest() && !originatedByReplay {
			res.Header().Set(replayHeaderKey, replayHeaderValue)
			http.Error(res, "Service Unavailable", http.StatusServiceUnavailable)
			return
		}

		req = req.WithContext(context.WithValue(req.Context(), "startTime", time.Now()))
		proxy.ServeHTTP(res, req)
	}
}

func serveHealthCheck(res http.ResponseWriter, req *http.Request) {
	if sampleFraction >= minSampleFraction {
		res.WriteHeader(http.StatusOK)
		res.Header().Set("Content-Type", "text/plain")
		_, _ = res.Write([]byte("OK")) // Write a response body
	} else {
		res.WriteHeader(http.StatusServiceUnavailable)
		res.Header().Set("Content-Type", "text/plain")
		_, _ = res.Write([]byte("Service Unavailable")) // Write a response body
	}
}

func main() {
	// Health check endpoint
	http.HandleFunc("/proxy_health", serveHealthCheck)

	// Reverse proxy endpoint
	http.HandleFunc("/", newReverseProxyHandler(setupReverseProxy(target)))

	// Start a goroutine for printing statistics periodically
	go func() {
		for {
			time.Sleep(5 * time.Second) // Wait for 5 seconds

			// Safely read shared variables
			mutex.Lock()
			currentLastRequestTime := lastRequestTime
			currentSampleFraction := sampleFraction
			currentAvgResponseTime := avgResponseTime
			mutex.Unlock()

			if time.Since(currentLastRequestTime) > 5*time.Second {
				log.Printf("No requests in the last 5 seconds. Resetting sample fraction to 0.5.\n")
				mutex.Lock()
				sampleFraction = 0.5
				mutex.Unlock()
			}

			// Print the desired statistics
			log.Printf("Average Response Time: %v\n", currentAvgResponseTime)
			log.Printf("Current Sample Fraction: %.2f%%\n", currentSampleFraction*100)
		}
	}()

	log.Printf("Listening on %s and proxying to %s\n", listenAddr, target)
	log.Printf("Health check responding on %s/health\n", listenAddr)
	if err := http.ListenAndServe(listenAddr, nil); err != nil {
		log.Fatal("ListenAndServe: ", err)
	}
}
