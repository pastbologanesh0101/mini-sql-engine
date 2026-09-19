-- Sample multi-statement script used by the script-mode end-to-end test.
CREATE TABLE users (id INTEGER, name TEXT, age INTEGER);
INSERT INTO users VALUES (1, 'Alice', 30);
INSERT INTO users VALUES (2, 'Bob', 25);
INSERT INTO users VALUES (3, 'Carol', 35);

SELECT * FROM users ORDER BY age DESC;

SELECT name FROM users WHERE age >= 30;

CREATE TABLE orders (order_id INTEGER, user_id INTEGER, amount INTEGER);
INSERT INTO orders VALUES (1, 1, 20);
INSERT INTO orders VALUES (2, 2, 40);

SELECT users.name, orders.amount FROM users JOIN orders ON users.id = orders.user_id;

SELECT user_id, SUM(amount) FROM orders GROUP BY user_id;
