package com.tutlinks.storefront.order;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {

    public record Item(int productId, int qty) {
    }

    public record PlaceOrder(int customerId, List<Item> items) {
    }

    public record Confirmation(long orderId, BigDecimal total, int lineCount) {
    }

    /** Mapped to HTTP 409 by {@code ApiExceptionHandler}. */
    public static class OutOfStockException extends RuntimeException {
        OutOfStockException(int productId) {
            super("product " + productId + " is out of stock");
        }
    }

    static final int MAX_LINES = 10;
    static final int MAX_QTY = 20;
    private static final int STATUS_PLACED = 0;

    private final JdbcClient jdbc;
    private final JdbcTemplate jdbcTemplate;

    OrderService(JdbcClient jdbc, JdbcTemplate jdbcTemplate) {
        this.jdbc = jdbc;
        this.jdbcTemplate = jdbcTemplate;
    }

    /**
     * Prices the order from the catalog, reserves stock, and writes the order and
     * its lines in one transaction.
     */
    @Transactional
    public Confirmation place(PlaceOrder order) {
        Map<Integer, Integer> quantities = validate(order);

        Map<Integer, BigDecimal> prices = new HashMap<>();
        jdbc.sql("SELECT id, price FROM product WHERE id IN (:ids)")
                .param("ids", quantities.keySet())
                .query(rs -> {
                    prices.put(rs.getInt(1), rs.getBigDecimal(2));
                });
        for (int productId : quantities.keySet()) {
            if (!prices.containsKey(productId)) {
                throw new IllegalArgumentException("product " + productId + " does not exist");
            }
        }

        // Stock rows are updated in ascending product order (TreeMap), so two orders
        // that share products cannot deadlock on each other.
        BigDecimal total = BigDecimal.ZERO;
        for (Map.Entry<Integer, Integer> entry : quantities.entrySet()) {
            int reserved = jdbc.sql("""
                            UPDATE inventory
                            SET stock = stock - ?, updated_at = NOW(3)
                            WHERE product_id = ? AND stock >= ?""")
                    .param(entry.getValue()).param(entry.getKey()).param(entry.getValue())
                    .update();
            if (reserved == 0) {
                throw new OutOfStockException(entry.getKey());
            }
            total = total.add(prices.get(entry.getKey()).multiply(BigDecimal.valueOf(entry.getValue())));
        }

        KeyHolder key = new GeneratedKeyHolder();
        jdbc.sql("""
                        INSERT INTO orders (customer_id, status, total, item_count, created_at)
                        VALUES (?, ?, ?, ?, NOW(3))""")
                .param(order.customerId()).param(STATUS_PLACED).param(total).param(quantities.size())
                .update(key);
        long orderId = key.getKey().longValue();

        List<Object[]> lines = new ArrayList<>(quantities.size());
        int lineNo = 1;
        for (Map.Entry<Integer, Integer> entry : quantities.entrySet()) {
            lines.add(new Object[] {orderId, lineNo++, entry.getKey(), entry.getValue(), prices.get(entry.getKey())});
        }
        jdbcTemplate.batchUpdate("""
                INSERT INTO order_item (order_id, line_no, product_id, qty, unit_price)
                VALUES (?, ?, ?, ?, ?)""", lines);

        return new Confirmation(orderId, total, quantities.size());
    }

    /** Validates the request and merges repeated products into one line each. */
    static Map<Integer, Integer> validate(PlaceOrder order) {
        if (order == null || order.items() == null || order.items().isEmpty()) {
            throw new IllegalArgumentException("an order needs at least one item");
        }
        if (order.customerId() < 1) {
            throw new IllegalArgumentException("customerId must be positive");
        }
        Map<Integer, Integer> quantities = new TreeMap<>(Comparator.naturalOrder());
        for (Item item : order.items()) {
            if (item.productId() < 1) {
                throw new IllegalArgumentException("productId must be positive");
            }
            if (item.qty() < 1 || item.qty() > MAX_QTY) {
                throw new IllegalArgumentException("qty must be between 1 and " + MAX_QTY);
            }
            int merged = quantities.merge(item.productId(), item.qty(), Integer::sum);
            if (merged > MAX_QTY) {
                throw new IllegalArgumentException("qty must be between 1 and " + MAX_QTY);
            }
        }
        if (quantities.size() > MAX_LINES) {
            throw new IllegalArgumentException("an order can have at most " + MAX_LINES + " lines");
        }
        return quantities;
    }
}
