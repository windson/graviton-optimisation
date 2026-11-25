package com.tutlinks.storefront.catalog;

import java.util.List;
import java.util.Optional;

import com.tutlinks.storefront.catalog.CatalogModels.BrandFacet;
import com.tutlinks.storefront.catalog.CatalogModels.Category;
import com.tutlinks.storefront.catalog.CatalogModels.DataSet;
import com.tutlinks.storefront.catalog.CatalogModels.PriceBand;
import com.tutlinks.storefront.catalog.CatalogModels.ProductDetail;
import com.tutlinks.storefront.catalog.CatalogModels.ProductSummary;
import com.tutlinks.storefront.catalog.CatalogModels.Review;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class CatalogRepository {

    /** Width, in currency units, of one price band in the listing facets. */
    static final int PRICE_BAND_WIDTH = 50;
    /** "Bought together" looks at this many of the most recent orders containing the product. */
    static final int ALSO_BOUGHT_ORDER_WINDOW = 300;

    private static final String SUMMARY_COLUMNS = "id, name, brand, price, rating, review_count, image";

    private static final RowMapper<ProductSummary> SUMMARY = (rs, n) -> new ProductSummary(
            rs.getInt("id"), rs.getString("name"), rs.getString("brand"), rs.getBigDecimal("price"),
            rs.getBigDecimal("rating"), rs.getInt("review_count"), rs.getString("image"));

    private final JdbcClient jdbc;

    CatalogRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public List<Category> categories() {
        return jdbc.sql("SELECT id, name, slug, product_count FROM category ORDER BY id")
                .query((rs, n) -> new Category(rs.getInt(1), rs.getString(2), rs.getString(3), rs.getInt(4)))
                .list();
    }

    /** One page of a category listing, read in the order of the index that matches the sort. */
    public List<ProductSummary> listing(int categoryId, Sort sort, String brand, int limit, int offset) {
        StringBuilder sql = new StringBuilder("SELECT ").append(SUMMARY_COLUMNS)
                .append(" FROM product WHERE category_id = ?");
        if (brand != null) {
            sql.append(" AND brand = ?");
        }
        sql.append(" ORDER BY ").append(sort.orderBy).append(" LIMIT ? OFFSET ?");
        JdbcClient.StatementSpec statement = jdbc.sql(sql.toString()).param(categoryId);
        if (brand != null) {
            statement = statement.param(brand);
        }
        return statement.param(limit).param(offset).query(SUMMARY).list();
    }

    public List<BrandFacet> brandFacets(int categoryId) {
        return jdbc.sql("""
                        SELECT brand, COUNT(*) AS n, MIN(price) AS min_price, MAX(price) AS max_price
                        FROM product
                        WHERE category_id = ?
                        GROUP BY brand
                        ORDER BY n DESC, brand
                        LIMIT 12""")
                .param(categoryId)
                .query((rs, n) -> new BrandFacet(rs.getString(1), rs.getInt(2), rs.getBigDecimal(3),
                        rs.getBigDecimal(4)))
                .list();
    }

    public List<PriceBand> priceBands(int categoryId) {
        return jdbc.sql("""
                        SELECT FLOOR(price / ?) AS band, COUNT(*) AS n
                        FROM product
                        WHERE category_id = ?
                        GROUP BY band
                        ORDER BY band""")
                .param(PRICE_BAND_WIDTH)
                .param(categoryId)
                .query((rs, n) -> {
                    int band = rs.getInt(1);
                    return new PriceBand(band * PRICE_BAND_WIDTH, (band + 1) * PRICE_BAND_WIDTH, rs.getInt(2));
                })
                .list();
    }

    public Optional<ProductDetail> product(int id) {
        return jdbc.sql("""
                        SELECT p.id, p.sku, p.name, p.brand, p.category_id, c.name AS category_name, p.price,
                               p.rating, p.review_count, p.description, p.image, i.stock
                        FROM product p
                        JOIN category c ON c.id = p.category_id
                        JOIN inventory i ON i.product_id = p.id
                        WHERE p.id = ?""")
                .param(id)
                .query((rs, n) -> new ProductDetail(rs.getInt("id"), rs.getString("sku"), rs.getString("name"),
                        rs.getString("brand"), rs.getInt("category_id"), rs.getString("category_name"),
                        rs.getBigDecimal("price"), rs.getBigDecimal("rating"), rs.getInt("review_count"),
                        rs.getString("description"), rs.getString("image"), rs.getInt("stock"),
                        List.of(), List.of()))
                .optional();
    }

    public List<Review> latestReviews(int productId, int limit) {
        return jdbc.sql("""
                        SELECT id, customer_id, rating, title, body, created_at
                        FROM review
                        WHERE product_id = ?
                        ORDER BY created_at DESC, id DESC
                        LIMIT ?""")
                .param(productId)
                .param(limit)
                .query((rs, n) -> new Review(rs.getLong(1), rs.getInt(2), rs.getInt(3), rs.getString(4),
                        rs.getString(5), rs.getTimestamp(6).toInstant()))
                .list();
    }

    /**
     * Products that most often share an order with the given product, counted over
     * the most recent orders that contain it. The window bounds the cost for
     * best-selling products.
     */
    public List<ProductSummary> alsoBought(int productId, int limit) {
        return jdbc.sql("""
                        SELECT p.id, p.name, p.brand, p.price, p.rating, p.review_count, p.image
                        FROM (
                            SELECT oi.product_id, COUNT(*) AS n
                            FROM (
                                SELECT order_id
                                FROM order_item
                                WHERE product_id = ?
                                ORDER BY order_id DESC
                                LIMIT ?
                            ) recent
                            JOIN order_item oi ON oi.order_id = recent.order_id
                            WHERE oi.product_id <> ?
                            GROUP BY oi.product_id
                            ORDER BY n DESC, oi.product_id
                            LIMIT ?
                        ) together
                        JOIN product p ON p.id = together.product_id
                        ORDER BY together.n DESC, p.id""")
                .param(productId)
                .param(ALSO_BOUGHT_ORDER_WINDOW)
                .param(productId)
                .param(limit)
                .query(SUMMARY)
                .list();
    }

    /** Prefix search ordered by popularity. The inner query is answered from the index alone. */
    public List<ProductSummary> searchByNamePrefix(String likePattern, int limit) {
        return jdbc.sql("""
                        SELECT p.id, p.name, p.brand, p.price, p.rating, p.review_count, p.image
                        FROM (
                            SELECT id
                            FROM product
                            WHERE name LIKE ?
                            ORDER BY review_count DESC, id
                            LIMIT ?
                        ) hit
                        JOIN product p ON p.id = hit.id
                        ORDER BY p.review_count DESC, p.id""")
                .param(likePattern)
                .param(limit)
                .query(SUMMARY)
                .list();
    }

    public List<ProductSummary> newArrivals(int limit) {
        return jdbc.sql("SELECT " + SUMMARY_COLUMNS + " FROM product ORDER BY created_at DESC, id LIMIT ?")
                .param(limit)
                .query(SUMMARY)
                .list();
    }

    public Optional<DataSet> dataSet() {
        return jdbc.sql("""
                        SELECT version, categories, products, customers, orders, max_order_id, reviews
                        FROM seed_meta
                        WHERE id = 1""")
                .query((rs, n) -> new DataSet(rs.getString(1), rs.getInt(2), rs.getInt(3), rs.getInt(4),
                        rs.getLong(5), rs.getLong(6), rs.getLong(7)))
                .optional();
    }

    /** Listing sort orders. Each one matches an index on {@code product}. */
    public enum Sort {
        RATING("rating DESC, id"),
        PRICE("price, id"),
        NEWEST("created_at DESC, id");

        final String orderBy;

        Sort(String orderBy) {
            this.orderBy = orderBy;
        }

        public static Sort parse(String value) {
            return switch (value == null ? "rating" : value) {
                case "rating" -> RATING;
                case "price" -> PRICE;
                case "newest" -> NEWEST;
                default -> throw new IllegalArgumentException("sort must be rating, price or newest");
            };
        }
    }
}
