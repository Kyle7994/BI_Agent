-- 001_schema.sql

CREATE TABLE users (
  id BIGINT PRIMARY KEY,
  email VARCHAR(255),
  country VARCHAR(64),
  signup_at DATETIME,
  channel VARCHAR(64),
  is_vip BOOLEAN
);

CREATE TABLE orders (
  id BIGINT PRIMARY KEY,
  user_id BIGINT,
  status VARCHAR(32),
  total_amount DECIMAL(10,2),
  created_at DATETIME,
  paid_at DATETIME,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE products (
  id BIGINT PRIMARY KEY,
  name VARCHAR(255),
  category VARCHAR(128),
  price DECIMAL(10,2),
  created_at DATETIME
);

CREATE TABLE order_items (
  id BIGINT PRIMARY KEY,
  order_id BIGINT,
  product_id BIGINT,
  quantity INT,
  unit_price DECIMAL(10,2),
  subtotal DECIMAL(10,2),
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (product_id) REFERENCES products(id)
);

INSERT INTO users VALUES
(1, 'alice@example.com', 'US', '2026-03-01 10:00:00', 'ads', true),
(2, 'bob@example.com', 'CA', '2026-03-02 11:00:00', 'organic', false),
(3, 'carol@example.com', 'US', '2026-03-03 12:00:00', 'referral', false);

INSERT INTO orders VALUES
(101, 1, 'paid', 120.50, '2026-03-10 09:00:00', '2026-03-10 09:05:00'),
(102, 2, 'paid', 80.00, '2026-03-11 10:00:00', '2026-03-11 10:02:00'),
(103, 1, 'refunded', 50.00, '2026-03-12 11:00:00', '2026-03-12 11:03:00'),
(104, 3, 'paid', 200.00, '2026-03-15 13:00:00', '2026-03-15 13:04:00');

INSERT INTO products VALUES
(1001, 'Phone Case', 'Accessories', 19.99, '2026-02-01 00:00:00'),
(1002, 'USB-C Cable', 'Accessories', 9.99, '2026-02-05 00:00:00'),
(1003, 'Bluetooth Speaker', 'Electronics', 49.99, '2026-02-10 00:00:00');

INSERT INTO order_items VALUES
(1, 101, 1001, 2, 19.99, 39.98),
(2, 101, 1002, 1, 9.99, 9.99),
(3, 102, 1002, 3, 9.99, 29.97),
(4, 104, 1003, 2, 49.99, 99.98);