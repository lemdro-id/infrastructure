package main

import (
	"fmt"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"sync"
	"sync/atomic"
	"time"
)

const (
	target                = "http://127.0.0.1:8536"
	listenAddr            = ":8080"
	maxResponseTimeTarget = 700 * time.Millisecond
	sampleSize            = 500
	minSampleFraction     = 0.10 // Always allow at least 1% of requests through
	replayHeaderKey       = "fly-replay"
	replayHeaderValue     = "elsewhere=true"
	replaySrcHeaderKey    = "fly-replay-src"
	emaAlpha              = 0.1
	IncreaseRate          = 0.05
	DecreaseRate          = 0.05
)

// Added a cache entry struct
type cacheEntry struct {
	content   []byte
	timestamp time.Time
}

var (
	sampleFraction            = int64(1.0 * 10000) // We'll use an int to store the percentage scaled up by 10,000
	currentRequestCount int64 = 0
	emaResponseTime     int64 = 0
	lastResponseTime          = time.Now().Unix()
	cache                     = struct {
		sync.RWMutex
		data map[string]*cacheEntry
	}{
		data: make(map[string]*cacheEntry),
	}
)

// Helper function to access the average response time safely
func getAvgResponseTime() time.Duration {
	avg := atomic.LoadInt64(&emaResponseTime)
	return time.Duration(avg)
}

func recordResponseTime(d time.Duration) {
	newResponseTime := int64(d)

	for {
		current := atomic.LoadInt64(&emaResponseTime)
		newEmaResponseTime := int64(float64(current)*(1-emaAlpha) + float64(newResponseTime)*emaAlpha)

		if atomic.CompareAndSwapInt64(&emaResponseTime, current, newEmaResponseTime) {
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
		originatedByReplay := response.Request.Header.Get(replaySrcHeaderKey) != ""
		if !originatedByReplay && (response.StatusCode >= http.StatusInternalServerError || response.StatusCode == http.StatusBadRequest) {
			response.Header.Set(replayHeaderKey, replayHeaderValue)
		}
		return nil
	}

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, e error) {
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
		if userAgent != "Consul Health Check" && !originatedByReplay && !shouldProcessRequest() {
			res.Header().Set(replayHeaderKey, replayHeaderValue)
			http.Error(res, "Service Unavailable", http.StatusServiceUnavailable)
			return
		}
		start := time.Now()
		proxy.ServeHTTP(res, req)
		recordResponseTime(time.Since(start))
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

func isIpInternal(ipAddress string) bool {
	ip := net.ParseIP(ipAddress)

	_, subnet1, _ := net.ParseCIDR("172.16.0.0/16")
	_, subnet2, _ := net.ParseCIDR("172.19.0.0/16")

	return subnet1.Contains(ip) || subnet2.Contains(ip)
}

func setCachedContent(path string, content []byte) {
	cache.Lock()
	defer cache.Unlock()

	cache.data[path] = &cacheEntry{
		content:   content,
		timestamp: time.Now(),
	}
}

func getCachedContent(path string) ([]byte, bool) {
	cache.RLock()
	defer cache.RUnlock()

	if entry, found := cache.data[path]; found {
		// Check if cache is valid within the 1 hour period
		if time.Since(entry.timestamp) < 1*time.Hour {
			return entry.content, true
		}
	}
	return nil, false
}

func cachedHandler(reverseProxy http.HandlerFunc) http.HandlerFunc {
	return func(res http.ResponseWriter, req *http.Request) {
		// Check if the requester's IP falls within the exempted range
		clientIP, _, _ := net.SplitHostPort(req.RemoteAddr)
		if isIpInternal(clientIP) {
			// If it's from your IPs, serve it using the reverse proxy without caching
			reverseProxy(res, req)
			return
		}

		// Try to serve from cache first
		if content, found := getCachedContent(req.URL.Path); found {
			if _, err := res.Write(content); err != nil {
				// Log the error and possibly take further action
				log.Printf("Error writing cached content to response: %v", err)
			}
			return
		}

		// Capture the response with a ResponseRecorder
		rw := httptest.NewRecorder()
		// Pass the request to the reverseProxy
		reverseProxy(rw, req)

		// Check and cache if response status is OK
		if rw.Code == http.StatusOK {
			setCachedContent(req.URL.Path, rw.Body.Bytes())
			res.Header().Set("Content-Type", "application/json")
			res.WriteHeader(http.StatusOK)
			if _, err := res.Write(rw.Body.Bytes()); err != nil {
				// Log the error and possibly take further action
				log.Printf("Error writing response content to client: %v", err)
			}
		} else {
			// If it's not OK, just replicate the recorded response
			for k, values := range rw.Header() {
				for _, v := range values {
					res.Header().Add(k, v)
				}
			}
			res.WriteHeader(rw.Code)
			if _, err := rw.Body.WriteTo(res); err != nil {
				// Log the error and possibly take further action
				log.Printf("Error replicating response to client: %v", err)
			}
		}
	}
}

func main() {
	// Health check endpoint
	http.HandleFunc("/proxy_health", serveHealthCheck)

	// Reverse proxy endpoint
	reverseProxy := newReverseProxyHandler(setupReverseProxy(target))
	http.HandleFunc("/nodeinfo/2.0.json", cachedHandler(reverseProxy))
	http.HandleFunc("/", reverseProxy)

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

	// Adjust sampleFraction on a timed interval in a separate routine
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond) // Adjust interval as needed
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				currentAvgResponseTime := getAvgResponseTime()

				currentSampleFractionScaled := atomic.LoadInt64(&sampleFraction)
				currentSampleFraction := float64(currentSampleFractionScaled) / 10000.0

				var newSampleFraction float64
				if currentAvgResponseTime > maxResponseTimeTarget {
					// response time too high, shed some load
					newSampleFraction = max(minSampleFraction, currentSampleFraction-DecreaseRate)
				} else {
					// response time low enough, gradually add load
					newSampleFraction = min(1.0, currentSampleFraction+IncreaseRate)
				}

				// Store the updated sampleFraction
				newSampleFractionScaled := int64(newSampleFraction * 10000)
				atomic.StoreInt64(&sampleFraction, newSampleFractionScaled)
			}
		}
	}()

	log.Printf("Listening on %s and proxying to %s\n", listenAddr, target)
	log.Printf("Health check responding on %s/health\n", listenAddr)
	if err := http.ListenAndServe(listenAddr, nil); err != nil {
		log.Fatal("ListenAndServe: ", err)
	}
}
