package com.tutlinks.storefront.customer;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class CustomerRepository {

    public record CartLine(int productId, String name, BigDecimal price, String image, int qty, int stock) {
    }

    public record Cart(int customerId, List<CartLine> lines, BigDecimal subtotal) {
    }

    public record OrderLine(int lineNo, int productId, String productName, int qty, BigDecimal unitPrice) {
    }

    public record OrderSummary(long id, int status, BigDecimal total, int itemCount, Instant createdAt,
                               List<OrderLine> lines) {
    }

    private final JdbcClient jdbc;

    CustomerRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Cart cart(int customerId) {
        List<CartLine> lines = jdbc.sql("""
                        SELECT ci.product_id, p.name, p.price, p.image, ci.qty, i.stock
                        FROM cart_item ci
                        JOIN product p ON p.id = ci.product_id
                        JOIN inventory i ON i.product_id = ci.product_id
                        WHERE ci.customer_id = ?
                        ORDER BY ci.updated_at DESC, ci.product_id""")
                .param(customerId)
                .query((rs, n) -> new CartLine(rs.getInt(1), rs.getString(2), rs.getBigDecimal(3),
                        rs.getString(4), rs.getInt(5), rs.getInt(6)))
                .list();
        BigDecimal subtotal = lines.stream()
                .map(line -> line.price().multiply(BigDecimal.valueOf(line.qty())))
                .reduce(BigDecimal.ZERO, BigDecimal::add);
        return new Cart(customerId, lines, subtotal);
    }

    public void putCartItem(int customerId, int productId, int qty) {
        if (qty == 0) {
            jdbc.sql("DELETE FROM cart_item WHERE customer_id = ? AND product_id = ?")
                    .param(customerId).param(productId).update();
            return;
        }
        jdbc.sql("""
                        INSERT INTO cart_item (customer_id, product_id, qty, updated_at)
                        VALUES (?, ?, ?, NOW(3))
                        ON DUPLICATE KEY UPDATE qty = VALUES(qty), updated_at = VALUES(updated_at)""")
                .param(customerId).param(productId).param(qty).update();
    }

    public boolean productExists(int productId) {
        return jdbc.sql("SELECT 1 FROM product WHERE id = ?").param(productId)
                .query((rs, n) -> 1).optional().isPresent();
    }

    /** The customer's most recent orders, each with its lines. Two queries, no per-order round trips. */
    public List<OrderSummary> recentOrders(int customerId, int limit) {
        Map<Long, OrderSummary> orders = new LinkedHashMap<>();
        jdbc.sql("""
                        SELECT id, status, total, item_count, created_at
                        FROM orders
                        WHERE customer_id = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT ?""")
                .param(customerId)
                .param(limit)
                .query(rs -> {
                    orders.put(rs.getLong(1), new OrderSummary(rs.getLong(1), rs.getInt(2), rs.getBigDecimal(3),
                            rs.getInt(4), rs.getTimestamp(5).toInstant(), new ArrayList<>()));
                });
        if (orders.isEmpty()) {
            return List.of();
        }
        jdbc.sql("""
                        SELECT oi.order_id, oi.line_no, oi.product_id, p.name, oi.qty, oi.unit_price
                        FROM order_item oi
                        JOIN product p ON p.id = oi.product_id
                        WHERE oi.order_id IN (:ids)
                        ORDER BY oi.order_id, oi.line_no""")
                .param("ids", orders.keySet())
                .query(rs -> {
                    orders.get(rs.getLong(1)).lines().add(new OrderLine(rs.getInt(2), rs.getInt(3),
                            rs.getString(4), rs.getInt(5), rs.getBigDecimal(6)));
                });
        return List.copyOf(orders.values());
    }
}
