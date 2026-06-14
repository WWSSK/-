# ── Stage 1: Build ──────────────────────────────────────────────
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/golang:1.22-alpine AS builder

ENV GOPROXY=https://goproxy.cn,direct
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

RUN apk add --no-cache protoc git

RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.34.1
RUN go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.4.0

WORKDIR /app

# Copy everything needed for the build.
COPY go.mod ./
COPY *.go ./
COPY proto/ proto/

# Generate protobuf Go code into pb/ (stripping module prefix from go_package).
RUN mkdir -p pb && \
    protoc --go_out=. --go_opt=module=points-service \
           --go-grpc_out=. --go-grpc_opt=module=points-service \
           proto/points.proto

# Resolve dependencies and build (go mod tidy fetches deps and generates go.sum).
RUN go mod tidy && \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /app/points-service .

# Download grpc_health_probe for Kubernetes health checks.
RUN GRPC_HEALTH_PROBE_VERSION=v0.4.24 && \
    wget --no-check-certificate -qO /app/grpc_health_probe \
    https://ghproxy.cn/https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64 && \
    chmod +x /app/grpc_health_probe

# ── Stage 2: Runtime ───────────────────────────────────────────
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/alpine:3.20

RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories
RUN apk add --no-cache ca-certificates tzdata && \
    adduser -D -u 1000 points

RUN mkdir -p /data && chown points:points /data

COPY --from=builder /app/points-service /app/points-service
COPY --from=builder /app/grpc_health_probe /app/grpc_health_probe

USER points
WORKDIR /app

EXPOSE 50054

ENV POINTS_SERVICE_PORT=50054
ENV POINTS_DB_PATH=/data/points.db

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/app/grpc_health_probe", "-addr=:50054"]

ENTRYPOINT ["/app/points-service"]
