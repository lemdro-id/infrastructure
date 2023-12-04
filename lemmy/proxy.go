package main

import (
	"context"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sync"
	"time"

	"github.com/shirou/gopsutil/cpu"
)

const (
	target                 = "http://127.0.0.1:8536"
	listenAddr             = ":80"
	responseTimeThreshold  = 500 * time.Millisecond
	cpuUsageThreshold      = 75.0 // Percent
	sampleSize             = 100
	recoverySampleFraction = 0.1 // Allow 10% of requests through for measuring
	replayHeaderKey        = "fly-replay"
	replayHeaderValue      = "elsewhere=true"
)

var (
	mutex            sync.Mutex
	times            = make([]time.Duration, 0, sampleSize)
	avgResponseTime  = time.Duration(0)
	overloaded       = false
	requestsMeasured = 0.0
)

func recordResponseTime(d time.Duration) {
	mutex.Lock()
	defer mutex.Unlock()

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
}

func checkSystemOverload() {
	mutex.Lock()
	defer mutex.Unlock()

	if avgResponseTime > responseTimeThreshold || isCPUOverloaded() {
		if !overloaded {
			overloaded = true
			requestsMeasured = 0
		}
	} else {
		overloaded = false
		requestsMeasured = 0
	}
}

func isCPUOverloaded() bool {
	percentages, err := cpu.Percent(time.Minute, false)
	if err != nil {
		log.Printf("Error retrieving CPU usage: %v", err)
		return false
	}
	// We use the first element in the slice assuming single CPU info is sufficient
	return percentages[0] > cpuUsageThreshold
}

func shouldProcessRequest() bool {
	mutex.Lock()
	defer mutex.Unlock()

	if !overloaded {
		return true
	}

	requestsMeasured++
	allowedMeasurements := recoverySampleFraction * float64(sampleSize)

	return requestsMeasured <= allowedMeasurements
}

func serveReverseProxy(res http.ResponseWriter, req *http.Request) {
	if !shouldProcessRequest() {
		res.Header().Set(replayHeaderKey, replayHeaderValue)
		http.Error(res, "Service Unavailable", http.StatusServiceUnavailable)
		return
	}

	targetUrl, err := url.Parse(target)
	if err != nil {
		http.Error(res, "Bad Gateway", http.StatusBadGateway)
		return
	}

	proxy := httputil.NewSingleHostReverseProxy(targetUrl)
	proxy.ModifyResponse = func(response *http.Response) error {
		recordResponseTime(time.Since(req.Context().Value("startTime").(time.Time)))
		checkSystemOverload()
		return nil
	}

	req = req.WithContext(context.WithValue(req.Context(), "startTime", time.Now()))
	proxy.ServeHTTP(res, req)
}

func serveHealthCheck(res http.ResponseWriter, req *http.Request) {
	if shouldProcessRequest() {
		res.WriteHeader(http.StatusOK)
	} else {
		res.WriteHeader(http.StatusServiceUnavailable)
	}
}

func main() {
	// Health check endpoint
	http.HandleFunc("/proxy_health", serveHealthCheck)

	// Reverse proxy endpoint
	http.HandleFunc("/", serveReverseProxy)

	log.Printf("Listening on %s and proxying to %s\n", listenAddr, target)
	log.Printf("Health check responding on %s/health\n", listenAddr)
	if err := http.ListenAndServe(listenAddr, nil); err != nil {
		log.Fatal("ListenAndServe: ", err)
	}
}
