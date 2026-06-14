package main

import (
	"database/sql"
	"fmt"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// Store manages points data persistence using SQLite.
type Store struct {
	mu sync.RWMutex
	db *sql.DB
}

// NewStore opens (or creates) the SQLite database and ensures the schema exists.
func NewStore(dbPath string) (*Store, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Connection pool — SQLite works best with a single writer.
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	s := &Store{db: db}
	if err := s.migrate(); err != nil {
		return nil, fmt.Errorf("failed to migrate schema: %w", err)
	}

	return s, nil
}

// migrate creates tables if they do not exist.
func (s *Store) migrate() error {
	queries := []string{
		`CREATE TABLE IF NOT EXISTS points (
			user_id      TEXT PRIMARY KEY,
			balance      INTEGER NOT NULL DEFAULT 0,
			total_earned INTEGER NOT NULL DEFAULT 0,
			total_spent  INTEGER NOT NULL DEFAULT 0
		)`,
		`CREATE TABLE IF NOT EXISTS transactions (
			transaction_id TEXT PRIMARY KEY,
			user_id        TEXT NOT NULL,
			type           TEXT NOT NULL CHECK(type IN ('EARN','REDEEM')),
			points         INTEGER NOT NULL,
			order_id       TEXT DEFAULT '',
			timestamp      TEXT NOT NULL
		)`,
		`CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, timestamp DESC)`,
	}

	for _, q := range queries {
		if _, err := s.db.Exec(q); err != nil {
			return fmt.Errorf("exec %q: %w", q, err)
		}
	}
	return nil
}

// Close closes the database connection.
func (s *Store) Close() error {
	return s.db.Close()
}

// ── Points CRUD ───────────────────────────────────────────────

// GetPoints returns the points row for a user. If the user does not exist,
// a zero-balance row is inserted automatically and returned.
func (s *Store) GetPoints(userID string) (*PointsRow, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Ensure the user row exists.
	_, err := s.db.Exec(
		`INSERT OR IGNORE INTO points (user_id) VALUES (?)`,
		userID,
	)
	if err != nil {
		return nil, fmt.Errorf("insert-or-ignore user: %w", err)
	}

	row := s.db.QueryRow(
		`SELECT user_id, balance, total_earned, total_spent FROM points WHERE user_id = ?`,
		userID,
	)

	var r PointsRow
	if err := row.Scan(&r.UserID, &r.Balance, &r.TotalEarned, &r.TotalSpent); err != nil {
		return nil, fmt.Errorf("scan points: %w", err)
	}
	return &r, nil
}

// EarnPoints adds points to a user's balance and records a transaction.
// Returns the number of points earned and the new balance.
func (s *Store) EarnPoints(userID, orderID string, points int64) (int64, int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	tx, err := s.db.Begin()
	if err != nil {
		return 0, 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	// Ensure user row exists.
	if _, err := tx.Exec(`INSERT OR IGNORE INTO points (user_id) VALUES (?)`, userID); err != nil {
		return 0, 0, fmt.Errorf("ensure user: %w", err)
	}

	// Update points.
	if _, err := tx.Exec(
		`UPDATE points SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?`,
		points, points, userID,
	); err != nil {
		return 0, 0, fmt.Errorf("update points: %w", err)
	}

	// Read back new balance.
	var newBalance int64
	if err := tx.QueryRow(
		`SELECT balance FROM points WHERE user_id = ?`, userID,
	).Scan(&newBalance); err != nil {
		return 0, 0, fmt.Errorf("read balance: %w", err)
	}

	// Record transaction.
	txID := fmt.Sprintf("%s-%s-%d", userID, orderID, time.Now().UnixNano())
	if _, err := tx.Exec(
		`INSERT INTO transactions (transaction_id, user_id, type, points, order_id, timestamp) VALUES (?, ?, 'EARN', ?, ?, ?)`,
		txID, userID, points, orderID, time.Now().UTC().Format(time.RFC3339),
	); err != nil {
		return 0, 0, fmt.Errorf("insert tx: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return 0, 0, fmt.Errorf("commit: %w", err)
	}

	return points, newBalance, nil
}

// RedeemPoints deducts points from a user's balance.
// Returns an error if the user does not have enough points.
func (s *Store) RedeemPoints(userID string, points int64) (int64, int64, float64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	tx, err := s.db.Begin()
	if err != nil {
		return 0, 0, 0, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	// Read current balance.
	var balance int64
	if err := tx.QueryRow(
		`SELECT balance FROM points WHERE user_id = ?`, userID,
	).Scan(&balance); err != nil {
		if err == sql.ErrNoRows {
			return 0, 0, 0, fmt.Errorf("user %s not found", userID)
		}
		return 0, 0, 0, fmt.Errorf("read balance: %w", err)
	}

	if balance < points {
		return 0, 0, 0, fmt.Errorf("insufficient points: have %d, need %d", balance, points)
	}

	// Deduct points.
	if _, err := tx.Exec(
		`UPDATE points SET balance = balance - ?, total_spent = total_spent + ? WHERE user_id = ?`,
		points, points, userID,
	); err != nil {
		return 0, 0, 0, fmt.Errorf("update points: %w", err)
	}

	newBalance := balance - points
	// 100 points = 1 unit of currency discount.
	discountAmount := float64(points) / 100.0

	// Record transaction.
	txID := fmt.Sprintf("%s-redeem-%d", userID, time.Now().UnixNano())
	if _, err := tx.Exec(
		`INSERT INTO transactions (transaction_id, user_id, type, points, order_id, timestamp) VALUES (?, ?, 'REDEEM', ?, '', ?)`,
		txID, userID, points, time.Now().UTC().Format(time.RFC3339),
	); err != nil {
		return 0, 0, 0, fmt.Errorf("insert tx: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return 0, 0, 0, fmt.Errorf("commit: %w", err)
	}

	return points, newBalance, discountAmount, nil
}

// GetHistory returns the most recent transactions for a user.
func (s *Store) GetHistory(userID string, limit int32) ([]TransactionRow, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	if limit <= 0 {
		limit = 20
	}

	rows, err := s.db.Query(
		`SELECT transaction_id, user_id, type, points, order_id, timestamp
		 FROM transactions
		 WHERE user_id = ?
		 ORDER BY timestamp DESC
		 LIMIT ?`,
		userID, limit,
	)
	if err != nil {
		return nil, fmt.Errorf("query transactions: %w", err)
	}
	defer rows.Close()

	var txs []TransactionRow
	for rows.Next() {
		var t TransactionRow
		if err := rows.Scan(&t.TransactionID, &t.UserID, &t.Type, &t.Points, &t.OrderID, &t.Timestamp); err != nil {
			return nil, fmt.Errorf("scan tx: %w", err)
		}
		txs = append(txs, t)
	}
	return txs, rows.Err()
}

// ── Row types ─────────────────────────────────────────────────

// PointsRow represents a row in the points table.
type PointsRow struct {
	UserID      string
	Balance     int64
	TotalEarned int64
	TotalSpent  int64
}

// TransactionRow represents a row in the transactions table.
type TransactionRow struct {
	TransactionID string
	UserID        string
	Type          string
	Points        int64
	OrderID       string
	Timestamp     string
}
