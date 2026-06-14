package main

import (
	"context"
	"log"
	"math"

	pb "points-service/pb"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// pointsServer implements the gRPC PointsServiceServer interface.
type pointsServer struct {
	pb.UnimplementedPointsServiceServer
	store *Store
}

// newPointsServer creates a new gRPC server instance backed by the given store.
func newPointsServer(store *Store) *pointsServer {
	return &pointsServer{store: store}
}

// ── GetPoints ─────────────────────────────────────────────────

func (s *pointsServer) GetPoints(ctx context.Context, req *pb.GetPointsRequest) (*pb.GetPointsResponse, error) {
	if req.UserId == "" {
		return nil, status.Error(codes.InvalidArgument, "user_id is required")
	}

	row, err := s.store.GetPoints(req.UserId)
	if err != nil {
		log.Printf("GetPoints(%s) error: %v", req.UserId, err)
		return nil, status.Error(codes.Internal, "failed to get points")
	}

	return &pb.GetPointsResponse{
		UserId:      row.UserID,
		Balance:     row.Balance,
		TotalEarned: row.TotalEarned,
		TotalSpent:  row.TotalSpent,
	}, nil
}

// ── EarnPoints ────────────────────────────────────────────────

func (s *pointsServer) EarnPoints(ctx context.Context, req *pb.EarnPointsRequest) (*pb.EarnPointsResponse, error) {
	if req.UserId == "" {
		return nil, status.Error(codes.InvalidArgument, "user_id is required")
	}
	if req.OrderId == "" {
		return nil, status.Error(codes.InvalidArgument, "order_id is required")
	}
	if req.OrderAmount <= 0 {
		return nil, status.Error(codes.InvalidArgument, "order_amount must be positive")
	}

	// Earn 1 point per unit of currency (rounded down).
	pointsEarned := int64(math.Floor(req.OrderAmount))

	earned, newBalance, err := s.store.EarnPoints(req.UserId, req.OrderId, pointsEarned)
	if err != nil {
		log.Printf("EarnPoints(%s, %s) error: %v", req.UserId, req.OrderId, err)
		return nil, status.Error(codes.Internal, "failed to earn points")
	}

	log.Printf("User %s earned %d points (order %s). New balance: %d",
		req.UserId, earned, req.OrderId, newBalance)

	return &pb.EarnPointsResponse{
		UserId:       req.UserId,
		PointsEarned: earned,
		NewBalance:   newBalance,
	}, nil
}

// ── RedeemPoints ──────────────────────────────────────────────

func (s *pointsServer) RedeemPoints(ctx context.Context, req *pb.RedeemPointsRequest) (*pb.RedeemPointsResponse, error) {
	if req.UserId == "" {
		return nil, status.Error(codes.InvalidArgument, "user_id is required")
	}
	if req.PointsToRedeem <= 0 {
		return nil, status.Error(codes.InvalidArgument, "points_to_redeem must be positive")
	}

	redeemed, newBalance, discount, err := s.store.RedeemPoints(req.UserId, req.PointsToRedeem)
	if err != nil {
		log.Printf("RedeemPoints(%s, %d) error: %v", req.UserId, req.PointsToRedeem, err)
		return &pb.RedeemPointsResponse{
			Success: false,
			Message: err.Error(),
		}, nil
	}

	log.Printf("User %s redeemed %d points. New balance: %d, discount: %.2f",
		req.UserId, redeemed, newBalance, discount)

	return &pb.RedeemPointsResponse{
		Success:         true,
		Message:         "points redeemed successfully",
		PointsRedeemed:  redeemed,
		NewBalance:      newBalance,
		DiscountAmount:  discount,
	}, nil
}

// ── GetHistory ────────────────────────────────────────────────

func (s *pointsServer) GetHistory(ctx context.Context, req *pb.GetHistoryRequest) (*pb.GetHistoryResponse, error) {
	if req.UserId == "" {
		return nil, status.Error(codes.InvalidArgument, "user_id is required")
	}

	txs, err := s.store.GetHistory(req.UserId, req.Limit)
	if err != nil {
		log.Printf("GetHistory(%s) error: %v", req.UserId, err)
		return nil, status.Error(codes.Internal, "failed to get history")
	}

	pbTxs := make([]*pb.PointsTransaction, 0, len(txs))
	for _, t := range txs {
		pbTxs = append(pbTxs, &pb.PointsTransaction{
			TransactionId: t.TransactionID,
			UserId:        t.UserID,
			Type:          t.Type,
			Points:        t.Points,
			OrderId:       t.OrderID,
			Timestamp:     t.Timestamp,
		})
	}

	return &pb.GetHistoryResponse{
		UserId:       req.UserId,
		Transactions: pbTxs,
	}, nil
}

// ── HealthCheck ───────────────────────────────────────────────

func (s *pointsServer) HealthCheck(ctx context.Context, req *pb.HealthCheckRequest) (*pb.HealthCheckResponse, error) {
	return &pb.HealthCheckResponse{
		Healthy: true,
		Message: "points-service is healthy",
	}, nil
}
