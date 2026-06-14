package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"

	pb "points-service/pb"

	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
)

const (
	defaultPort   = "50054"
	defaultDBPath = "/data/points.db"
)

func main() {
	port := envOrDefault("POINTS_SERVICE_PORT", defaultPort)
	dbPath := envOrDefault("POINTS_DB_PATH", defaultDBPath)

	log.Printf("Starting Points Service...")
	log.Printf("  gRPC port : %s", port)
	log.Printf("  Database  : %s", dbPath)

	// Initialize SQLite store.
	store, err := NewStore(dbPath)
	if err != nil {
		log.Fatalf("Failed to initialize store: %v", err)
	}
	defer store.Close()
	log.Println("Database initialized successfully.")

	// Create gRPC server.
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen on port %s: %v", port, err)
	}

	grpcServer := grpc.NewServer(
		grpc.MaxRecvMsgSize(4*1024*1024),
		grpc.MaxSendMsgSize(4*1024*1024),
	)

	// Register PointsService.
	pb.RegisterPointsServiceServer(grpcServer, newPointsServer(store))

	// Register standard gRPC health check for Kubernetes probes.
	healthServer := health.NewServer()
	healthServer.SetServingStatus("", grpc_health_v1.HealthCheckResponse_SERVING)
	grpc_health_v1.RegisterHealthServer(grpcServer, healthServer)

	// Enable server reflection for debugging with grpcurl.
	reflection.Register(grpcServer)

	// Graceful shutdown on SIGTERM / SIGINT.
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
		<-sigCh
		log.Println("Shutting down gracefully...")
		grpcServer.GracefulStop()
	}()

	log.Printf("Points Service listening on :%s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("gRPC server error: %v", err)
	}
}

func envOrDefault(key, defaultVal string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultVal
}
