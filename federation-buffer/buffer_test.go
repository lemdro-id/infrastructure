package main

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRequestForwardingFlow(t *testing.T) {
	// Setup fake forward host
	fakeServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Confirm the request has been received
		body, err := io.ReadAll(r.Body)
		require.NoError(t, err, "Reading request body failed")
		assert.True(t, strings.Contains(string(body), "TestRequestBody"), "Body does not contain expected content")

		// Respond
		w.WriteHeader(http.StatusOK)
	}))
	defer fakeServer.Close()

	// Configure FORWARD_HOST to point to our fake server
	os.Setenv("FORWARD_HOST", fakeServer.URL[7:]) // Remove 'http://' from URL
	print(fakeServer.URL[7:])
	defer os.Unsetenv("FORWARD_HOST")

	// Re-initialize to apply the test environment variables
	SetForwardHost()

	// Start the forwarding goroutine
	go ForwardRequest()

	// Create an httptest Server with the handler to simulate `/inbox` endpoint
	testServer := httptest.NewServer(http.HandlerFunc(EnqueueRequest))
	defer testServer.Close()

	// Make a request to the `/inbox` handler to simulate an incoming request
	requestBody := bytes.NewBufferString("TestRequestBody")
	resp, err := http.Post(testServer.URL+"/inbox", "application/text", requestBody)
	require.NoError(t, err, "Making POST request failed")
	defer resp.Body.Close()

	// Ensure the `/inbox` endpoint is responding as expected
	assert.Equal(t, http.StatusOK, resp.StatusCode, "Expected HTTP 200 OK response")

	waitForQueueToBeEmpty(2 * time.Second)
}

// Utility to monitor the queue size and block until it's empty or a timeout occurs.
// Useful if you want to wait for the queue to be processed before making assertions.
func waitForQueueToBeEmpty(timeout time.Duration) bool {
	start := time.Now()
	for {
		if GetRequestQueueLength() == 0 {
			return true
		}
		if time.Since(start) > timeout {
			return false
		}
		time.Sleep(50 * time.Millisecond) // Avoid tight loop
	}
}
