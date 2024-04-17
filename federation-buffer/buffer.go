package main

import (
	"bufio"
	"bytes"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"os"
	"sync"
	"time"
)

var (
	requestQueue    chan []byte
	forwardHost     string
	listenPort      string = "8080"
	mu              sync.Mutex
	averageResponse time.Duration
	responseSamples int64
	previousSize    int
	sizeChangeRate  int // Tracks how fast the queue size is changing
	lastMeasurement time.Time
)

func init() {
	SetForwardHostAndPort()
	requestQueue = make(chan []byte, 10000) // buffer limit
	lastMeasurement = time.Now()
}

func GetRequestQueueLength() int {
	return len(requestQueue)
}

func SetForwardHostAndPort() {
	forwardHost = os.Getenv("FORWARD_HOST")
	if forwardHost == "" {
		panic("FORWARD_HOST environment variable must be set")
	}
	envPort := os.Getenv("PORT")
	if envPort != "" {
		listenPort = envPort
	}
}

func EnqueueRequest(w http.ResponseWriter, r *http.Request) {
	dump, err := httputil.DumpRequest(r, true)
	if err != nil {
		http.Error(w, "Failed to dump request", http.StatusInternalServerError)
		return
	}

	// Enqueue the serialized request
	requestQueue <- dump

	w.WriteHeader(http.StatusOK)
}

func ForwardRequest() {
	for dumpedRequest := range requestQueue {
		client := &http.Client{}
		startTime := time.Now()

		// Reconstruct the request from the dumped bytes
		buffer := bytes.NewBuffer(dumpedRequest)
		req, err := http.ReadRequest(bufio.NewReader(buffer))
		if err != nil {
			log.Printf("Failed to reconstruct request: %v\n", err)
			continue
		}

		// Update the URL with the forward host
		req.RequestURI = "" // Clear the RequestURI to avoid request error on client.Do
		req.URL.Scheme = "http"
		req.URL.Host = forwardHost

		// Forward the reconstructed request
		resp, err := client.Do(req)
		if err != nil {
			log.Printf("Failed to forward request: %v\n", err)
			continue
		}
		// Ensure response body is closed, capturing any errors
		if err := resp.Body.Close(); err != nil {
			log.Printf("Error closing response body: %v\n", err)
		}

		// Calculate and update stats after forwarding is complete
		duration := time.Since(startTime)
		UpdateStats(duration)
	}
}

func UpdateStats(duration time.Duration) {
	mu.Lock()
	defer mu.Unlock()

	newSize := GetRequestQueueLength()
	currentTime := time.Now()

	responseSamples++
	averageResponse += (duration - averageResponse) / time.Duration(responseSamples) // Rolling average calculation

	// Update rate if at least a second has passed since last measurement
	if currentTime.Sub(lastMeasurement) >= time.Second {
		sizeChangeRate = newSize - previousSize
		previousSize = newSize
		lastMeasurement = currentTime
	}
}

func PrintStats() {
	ticker := time.NewTicker(10 * time.Second)
	for {
		select {
		case <-ticker.C:
			mu.Lock()
			fmt.Printf("[%v] [Stats] Buffer Size: %d, Size Change Rate: %d/sec, Avg Response Time: %v\n", time.Now().Format("2006-01-02 15:04:05"), len(requestQueue), sizeChangeRate, averageResponse)
			mu.Unlock()
		}
	}
}

func serveHealthCheck(res http.ResponseWriter, req *http.Request) {
	res.WriteHeader(http.StatusOK)
}

func main() {
	go ForwardRequest()
	go PrintStats()

	http.HandleFunc("/inbox", EnqueueRequest)
	http.HandleFunc("/proxy_health", serveHealthCheck)
	fmt.Println("Reverse proxy started. Listening on port 8080...")
	if err := http.ListenAndServe(":8080", nil); err != nil {
		fmt.Printf("Failed to start server: %v\n", err)
		os.Exit(1)
	}
}
