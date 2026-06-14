# Points Service — Online Boutique 积分服务

> **成员 B (微服务开发组)** — 为 Online-Boutique 微服务系统新增的积分/忠诚度服务。
>
> 该服务使系统从**第二档（部署开源微服务）**跃升至**第三档（微服务开发）**。

---

## 一、服务概述

Points Service 是一个基于 **gRPC** 的微服务，为 Online-Boutique 电商平台提供用户积分管理功能：

| 功能 | 说明 |
|------|------|
| **积分查询** | 查询用户的当前积分余额、累计获取、累计使用 |
| **积分获取** | 用户完成订单后自动获得积分（1元 = 1积分） |
| **积分兑换** | 用户可使用积分抵扣订单金额（100积分 = 1元） |
| **积分历史** | 查询用户的积分变动记录 |

### 技术栈

| 层级 | 技术 |
|------|------|
| 通信协议 | gRPC + Protocol Buffers |
| 编程语言 | Go 1.22 |
| 数据存储 | SQLite (pure Go, 无CGO依赖) |
| 容器化 | Docker (多阶段构建) |
| 编排部署 | Kubernetes |

---

## 二、项目结构

```
points-service/
├── proto/
│   └── points.proto          # Protobuf 服务定义
├── main.go                    # 服务入口
├── server.go                  # gRPC 服务实现
├── store.go                   # SQLite 数据层
├── go.mod                     # Go 模块定义
├── gen.sh                     # Proto 代码生成脚本
├── Dockerfile                 # 多阶段 Docker 构建
├── kubernetes/
│   └── points-service.yaml    # K8s 部署清单
└── README.md                  # 本文档
```

---

## 三、gRPC API 文档

### 3.1 GetPoints — 查询积分

```protobuf
rpc GetPoints(GetPointsRequest) returns (GetPointsResponse);
```

**Request:**
```json
{ "user_id": "user-123" }
```

**Response:**
```json
{
  "user_id": "user-123",
  "balance": 1500,
  "total_earned": 3500,
  "total_spent": 2000
}
```

### 3.2 EarnPoints — 获取积分（下单后调用）

```protobuf
rpc EarnPoints(EarnPointsRequest) returns (EarnPointsResponse);
```

**Request:**
```json
{
  "user_id": "user-123",
  "order_id": "order-456",
  "order_amount": 299.99
}
```

**Response:**
```json
{
  "user_id": "user-123",
  "points_earned": 299,
  "new_balance": 1799
}
```

### 3.3 RedeemPoints — 兑换积分

```protobuf
rpc RedeemPoints(RedeemPointsRequest) returns (RedeemPointsResponse);
```

**Request:**
```json
{
  "user_id": "user-123",
  "points_to_redeem": 500
}
```

**Response (成功):**
```json
{
  "success": true,
  "message": "points redeemed successfully",
  "points_redeemed": 500,
  "new_balance": 1299,
  "discount_amount": 5.00
}
```

**Response (失败 — 积分不足):**
```json
{
  "success": false,
  "message": "insufficient points: have 200, need 500"
}
```

### 3.4 GetHistory — 积分历史

```protobuf
rpc GetHistory(GetHistoryRequest) returns (GetHistoryResponse);
```

**Request:**
```json
{ "user_id": "user-123", "limit": 10 }
```

**Response:**
```json
{
  "user_id": "user-123",
  "transactions": [
    {
      "transaction_id": "user-123-order-456-1718320000000000000",
      "user_id": "user-123",
      "type": "EARN",
      "points": 299,
      "order_id": "order-456",
      "timestamp": "2026-06-14T10:00:00Z"
    }
  ]
}
```

---

## 四、与 Online-Boutique 的集成

### 4.1 服务调用关系

```
                    ┌──────────────────┐
                    │    frontend       │
                    │    (Go, HTTP)     │
                    └───┬──────────┬────┘
                        │          │
           GetPoints ───┤          │─── EarnPoints
         RedeemPoints   │          │    GetHistory
                        │          │
              ┌─────────▼──────────▼─────────┐
              │       checkoutservice         │
              │       (Go, gRPC)              │
              └───────────────────────────────┘
                              │
                              │ EarnPoints (after payment success)
                              ▼
              ┌───────────────────────────────┐
              │     ★ points-service ★        │
              │     (Go, gRPC)                │
              │     Port: 50054               │
              └───────────────────────────────┘
```

### 4.2 集成点说明

1. **frontend → points-service (GetPoints)**
   - 在用户个人中心页面展示当前积分余额
   - URL: `grpc://points-service.online-boutique:50054`

2. **frontend → points-service (RedeemPoints)**
   - 在结算页面提供"使用积分抵扣"选项
   - 显示可抵扣金额，确认后扣除积分

3. **checkoutservice → points-service (EarnPoints)**
   - 订单支付成功后，按订单金额 1:1 发放积分
   - 需在 checkoutservice 的 `PlaceOrder` 流程最后添加此调用

### 4.3 修改现有服务的建议

**checkoutservice 集成示例**（Go伪代码）：
```go
import pointsPb "points-service/pb"

// 在 PlaceOrder 成功后调用
pointsClient := pointsPb.NewPointsServiceClient(conn)
resp, err := pointsClient.EarnPoints(ctx, &pointsPb.EarnPointsRequest{
    UserId:      req.UserId,
    OrderId:     orderId,
    OrderAmount: totalAmount,
})
```

**frontend 查询积分示例**（Go伪代码）：
```go
pointsClient := pointsPb.NewPointsServiceClient(conn)
resp, err := pointsClient.GetPoints(ctx, &pointsPb.GetPointsRequest{
    UserId: sessionId,
})
// 在页面上展示 resp.Balance
```

---

## 五、构建与部署

### 5.1 构建 Docker 镜像

```bash
cd points-service

# 构建镜像
docker build -t yourdockerhub/points-service:v1 .

# 推送到 Docker Hub
docker push yourdockerhub/points-service:v1
```

### 5.2 部署到 Kubernetes

```bash
# 1. 修改 kubernetes/points-service.yaml 中的镜像地址
#    image: yourdockerhub/points-service:v1

# 2. 部署到 Minikube 集群
kubectl apply -f kubernetes/points-service.yaml

# 3. 验证部署
kubectl get pods -n online-boutique -l app=points-service
kubectl logs -n online-boutique -l app=points-service

# 4. 验证 gRPC 服务（使用 grpcurl）
kubectl port-forward -n online-boutique svc/points-service 50054:50054
grpcurl -plaintext localhost:50054 list
grpcurl -plaintext -d '{"user_id":"test123"}' localhost:50054 points.PointsService/GetPoints
```

### 5.3 本地开发

```bash
# 1. 生成 protobuf 代码
chmod +x gen.sh && ./gen.sh

# 2. 下载依赖
go mod tidy

# 3. 运行服务
go run .
```

---

## 六、配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `POINTS_SERVICE_PORT` | `50054` | gRPC 服务端口 |
| `POINTS_DB_PATH` | `/data/points.db` | SQLite 数据库文件路径 |

---

## 七、测试验证

### 使用 grpcurl 测试

```bash
# 端口转发
kubectl port-forward -n online-boutique svc/points-service 50054:50054 &

# 健康检查
grpcurl -plaintext localhost:50054 points.PointsService/HealthCheck

# 查询积分（新用户余额为0）
grpcurl -plaintext -d '{"user_id":"alice"}' \
  localhost:50054 points.PointsService/GetPoints

# 获取积分
grpcurl -plaintext -d '{"user_id":"alice","order_id":"ord-001","order_amount":299.99}' \
  localhost:50054 points.PointsService/EarnPoints

# 再次查询积分
grpcurl -plaintext -d '{"user_id":"alice"}' \
  localhost:50054 points.PointsService/GetPoints

# 兑换积分
grpcurl -plaintext -d '{"user_id":"alice","points_to_redeem":100}' \
  localhost:50054 points.PointsService/RedeemPoints

# 查看历史
grpcurl -plaintext -d '{"user_id":"alice","limit":10}' \
  localhost:50054 points.PointsService/GetHistory
```

### 使用 Selenium / JMeter 测试

该服务完全通过 gRPC 接口调用，可以配合：
- **JMeter**: 使用 gRPC Sampler 插件进行压力测试
- **Selenium**: 通过前端页面间接测试（积分显示、兑换操作）
- **Prometheus**: 需额外配置 gRPC metrics exporter 采集指标

---

## 八、交付清单

| 序号 | 交付物 | 状态 |
|------|--------|------|
| 1 | Docker 镜像 `yourdockerhub/points-service:v1` | 需推送至 Docker Hub |
| 2 | K8s 部署 YAML `kubernetes/points-service.yaml` | ✅ 已完成 |
| 3 | Proto 定义文件 `proto/points.proto` | ✅ 已完成 |
| 4 | 服务源码 (Go) | ✅ 已完成 |
| 5 | README 文档 | ✅ 已完成 |

### 部署命令（成员 A 执行）

```bash
kubectl apply -f kubernetes/points-service.yaml
```

> **注意**: 部署前请将 `kubernetes/points-service.yaml` 中的 `image` 字段
> 替换为实际的 Docker Hub 镜像地址。
