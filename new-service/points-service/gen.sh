#!/bin/bash
# ──────────────────────────────────────────────────────────────
# Generate protobuf Go code from proto/points.proto
# Requires: protoc, protoc-gen-go, protoc-gen-go-grpc
#
# If you don't have these installed locally, use Docker:
#   docker run --rm -v "$(pwd):/workspace" -w /workspace \
#     golang:1.22-alpine sh -c '
#       apk add --no-cache protoc git
#       go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.34.1
#       go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.4.0
#       export PATH=$PATH:/root/go/bin
#       mkdir -p pb
#       protoc --go_out=. --go_opt=module=points-service \
#              --go-grpc_out=. --go-grpc_opt=module=points-service \
#              proto/points.proto
#     '
# ──────────────────────────────────────────────────────────────
set -e

echo "Generating protobuf Go code..."

mkdir -p pb

protoc \
    --go_out=. \
    --go_opt=module=points-service \
    --go-grpc_out=. \
    --go-grpc_opt=module=points-service \
    proto/points.proto

echo "Done! Generated files in pb/"
ls -la pb/
