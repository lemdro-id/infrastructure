package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sync"
	"sync/atomic"
	"time"
)

const (
	target                 = "http://127.0.0.1:8536"
	listenAddr             = ":8080"
	responseTimeTarget     = 500 * time.Millisecond
	sampleSize             = 500
	minSampleFraction      = 0.10 // Always allow at least 1% of requests through
	replayHeaderKey        = "fly-replay"
	replayHeaderValue      = "elsewhere=true"
	replaySrcHeaderKey     = "fly-replay-src"
	emaAlpha               = 0.1
	FractionAdjustmentRate = 0.001
)

var (
	mutex               sync.Mutex
	sampleFraction            = int64(1.0 * 10000) // We'll use an int to store the percentage scaled up by 10,000
	currentRequestCount int64 = 0
	emaResponseTime     int64 = 0
	lastResponseTime    int64 = time.Now().Unix()
)

// Helper function to access the average response time safely
func getAvgResponseTime() time.Duration {
	avg := atomic.LoadInt64(&emaResponseTime)
	return time.Duration(avg)
}

func recordResponseTime(d time.Duration) {
	mutex.Lock()
	defer mutex.Unlock()

	newResponseTime := int64(d)

	for {
		current := atomic.LoadInt64(&emaResponseTime)
		newEmaResponseTime := int64(float64(current)*(1-emaAlpha) + float64(newResponseTime)*emaAlpha)

		if atomic.CompareAndSwapInt64(&emaResponseTime, current, newEmaResponseTime) {
			currentAvg := time.Duration(newEmaResponseTime)
			// Load the current sampleFraction
			currentSampleFractionScaled := atomic.LoadInt64(&sampleFraction)
			currentSampleFraction := float64(currentSampleFractionScaled) / 10000.0

			var newSampleFraction float64
			if currentAvg > responseTimeTarget {
				// response time too high, shed some load
				newSampleFraction = max(minSampleFraction, currentSampleFraction-FractionAdjustmentRate)
			} else {
				// response time low enough, gradually add load
				newSampleFraction = min(1.0, currentSampleFraction+FractionAdjustmentRate)
			}

			// Store the updated sampleFraction
			newSampleFractionScaled := int64(newSampleFraction * 10000)
			atomic.StoreInt64(&sampleFraction, newSampleFractionScaled)

			break
		}
	}

	response := time.Now().Unix()
	atomic.StoreInt64(&lastResponseTime, response)
}

func shouldProcessRequest() bool {
	// Load the current sampleFraction
	currentSampleFractionScaled := atomic.LoadInt64(&sampleFraction)
	currentSampleFraction := float64(currentSampleFractionScaled) / 10000.0

	// skip load checking if we are accepting all requests
	if currentSampleFraction == 1.0 {
		return true
	}

	allowedRequestCount := int(currentSampleFraction * float64(sampleSize))

	// Since currentRequestCount variable is also shared we need to use atomic operations for it
	// Convert the count to an atomic variable as well
	currentRequestCountLocal := atomic.AddInt64(&currentRequestCount, 1)

	// Restart the count whenever it exceeds sampleSize
	if currentRequestCountLocal >= int64(sampleSize) {
		atomic.StoreInt64(&currentRequestCount, 0)
		return false
	}

	return currentRequestCountLocal <= int64(allowedRequestCount)
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
		userAgent := req.Header.Get("User-Agent")

		// Exempt "Consul Health Check" User-Agent from load shedding
		if userAgent != "Consul Health Check" && !shouldProcessRequest() && !originatedByReplay {
			res.Header().Set(replayHeaderKey, replayHeaderValue)
			http.Error(res, "Service Unavailable", http.StatusServiceUnavailable)
			return
		}

		req = req.WithContext(context.WithValue(req.Context(), "startTime", time.Now()))
		proxy.ServeHTTP(res, req)
	}
}

func serveHealthCheck(res http.ResponseWriter, req *http.Request) {
	// Load the sampleFraction atomically and convert it back to a floating-point percentage
	currentSampleFractionScaled := atomic.LoadInt64(&sampleFraction)
	currentSampleFraction := float64(currentSampleFractionScaled) / 10000.0 // unscale it

	if currentSampleFraction >= minSampleFraction {
		res.WriteHeader(http.StatusOK)
		res.Header().Set("Content-Type", "text/plain")
		_, _ = res.Write([]byte("OK")) // Write a response body
	} else {
		res.WriteHeader(http.StatusServiceUnavailable)
		res.Header().Set("Content-Type", "text/plain")
		responseText := fmt.Sprintf("Service Unavailable - Average Response Time: %v", getAvgResponseTime())
		_, _ = res.Write([]byte(responseText)) // Write the response body
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
			currentLastResponseTime := time.Unix(atomic.LoadInt64(&lastResponseTime), 0)
			currentAvgResponseTime := getAvgResponseTime()
			// Load sampleFraction atomically and convert it to percentage
			currentSampleFractionScaled := atomic.LoadInt64(&sampleFraction)
			currentSampleFraction := float64(currentSampleFractionScaled) / 10000.0

			if currentSampleFraction < 1.0 && time.Since(currentLastResponseTime) > 5*time.Second {
				atomic.StoreInt64(&sampleFraction, int64(0.5*10000))
				atomic.StoreInt64(&emaResponseTime, 0)
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
