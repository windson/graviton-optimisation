package com.tutlinks.storefront.seed;

import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Generates the study's data set inside the database with INSERT ... SELECT
 * statements, so no rows travel over the network. Runs when
 * {@code storefront.seed.enabled=true} (a Kubernetes Job in the cluster) and does
 * nothing if the same seed version is already loaded.
 *
 * <p>Every value is a hash of the row number, so two runs with the same sizes
 * produce the same data.
 */
@Component
@ConditionalOnProperty(name = "storefront.seed.enabled", havingValue = "true")
class SeedRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(SeedRunner.class);

    /** Rows produced by one statement. Keeps each transaction to a manageable size. */
    private static final int CHUNK = 1_000_000;
    private static final int PRODUCT_CHUNK = 250_000;
    /** All generated timestamps are relative to this instant, not to the time the seed ran. */
    private static final String EPOCH = "'2026-11-01 00:00:00'";
    private static final long TWO_YEARS_SECONDS = 63_072_000L;

    private static final String[] TABLES = {
        "category", "product", "inventory", "customer", "orders", "order_item", "review", "cart_item"};

    private final JdbcTemplate jdbc;
    private final SeedProperties seed;

    SeedRunner(JdbcTemplate jdbc, SeedProperties seed) {
        this.jdbc = jdbc;
        this.seed = seed;
    }

    @Override
    public void run(ApplicationArguments args) throws Exception {
        Integer loaded = jdbc.queryForObject(
                "SELECT COUNT(*) FROM seed_meta WHERE id = 1 AND version = ?", Integer.class, seed.version());
        if (loaded != null && loaded > 0) {
            log.info("seed {} already loaded, nothing to do", seed.version());
            return;
        }
        log.info("seeding {}: categories={} products={} customers={} orders={} reviews={}", seed.version(),
                seed.categories(), seed.products(), seed.customers(), seed.orders(), seed.reviews());
        long started = System.nanoTime();

        jdbc.update("DELETE FROM seed_meta");
        for (String table : TABLES) {
            jdbc.execute("TRUNCATE TABLE " + table);
        }
        createSequence();

        step("category", List.of(categorySql()));
        step("product", chunks(seed.products(), PRODUCT_CHUNK, this::productSql));
        step("category counts", List.of("""
                UPDATE category c
                JOIN (SELECT category_id, COUNT(*) AS n FROM product GROUP BY category_id) x ON x.category_id = c.id
                SET c.product_count = x.n"""));
        step("inventory", List.of("""
                INSERT INTO inventory (product_id, stock, updated_at)
                SELECT id, 1000000, %s FROM product""".formatted(EPOCH)));
        step("customer", chunks(seed.customers(), CHUNK, this::customerSql));
        step("orders", chunks(seed.orders(), CHUNK, this::ordersSql));
        step("order_item", chunks(seed.orders(), CHUNK, this::orderItemSql));
        step("review", chunks(seed.reviews(), CHUNK, this::reviewSql));
        step("cart_item", chunks(seed.customers(), CHUNK, this::cartSql));

        List<String> analyze = new ArrayList<>();
        for (String table : TABLES) {
            analyze.add("ANALYZE TABLE " + table);
        }
        step("analyze", analyze);

        jdbc.execute("DROP TABLE seed_seq");
        jdbc.execute("DROP TABLE seed_digit");
        jdbc.update("""
                INSERT INTO seed_meta (id, version, categories, products, customers, orders, max_order_id, reviews,
                                       completed_at)
                VALUES (1, ?, ?, ?, ?, ?, (SELECT MAX(id) FROM orders), ?, NOW())""",
                seed.version(), seed.categories(), seed.products(), seed.customers(), seed.orders(), seed.reviews());
        log.info("seed {} complete in {} s", seed.version(), (System.nanoTime() - started) / 1_000_000_000L);
    }

    /** A table holding 0..999,999, used as the row source of every generator statement. */
    private void createSequence() {
        jdbc.execute("DROP TABLE IF EXISTS seed_seq");
        jdbc.execute("DROP TABLE IF EXISTS seed_digit");
        jdbc.execute("CREATE TABLE seed_digit (d INT NOT NULL PRIMARY KEY)");
        jdbc.execute("INSERT INTO seed_digit VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9)");
        jdbc.execute("CREATE TABLE seed_seq (n INT NOT NULL PRIMARY KEY)");
        jdbc.execute("""
                INSERT INTO seed_seq (n)
                SELECT a.d + 10 * b.d + 100 * c.d + 1000 * d.d + 10000 * e.d + 100000 * f.d
                FROM seed_digit a, seed_digit b, seed_digit c, seed_digit d, seed_digit e, seed_digit f
                ORDER BY 1""");
    }

    private void step(String name, List<String> statements) throws Exception {
        long started = System.nanoTime();
        ExecutorService pool = Executors.newFixedThreadPool(Math.min(seed.parallelism(), statements.size()));
        try {
            List<Future<Integer>> results = new ArrayList<>();
            for (String sql : statements) {
                // execute() rather than update(): ANALYZE TABLE returns a result set.
                results.add(pool.submit(() -> jdbc.execute((Statement statement) -> {
                    statement.execute(sql);
                    return Math.max(statement.getUpdateCount(), 0);
                })));
            }
            long rows = 0;
            for (Future<Integer> result : results) {
                rows += result.get();
            }
            log.info("{}: {} rows in {} s", name, rows, (System.nanoTime() - started) / 1_000_000_000L);
        } finally {
            pool.shutdownNow();
        }
    }

    private interface ChunkSql {
        String sql(long from, long count);
    }

    /** Splits [0, total) into chunks and builds one statement per chunk. */
    private static List<String> chunks(long total, int size, ChunkSql builder) {
        List<String> statements = new ArrayList<>();
        for (long from = 0; from < total; from += size) {
            statements.add(builder.sql(from, Math.min(size, total - from)));
        }
        return statements;
    }

    // ---- generator statements ---------------------------------------------------------

    private String categorySql() {
        return """
                INSERT INTO category (id, name, slug, product_count)
                SELECT n + 1, CONCAT(%s, ' ', %s), CONCAT('category-', n + 1), 0
                FROM seed_seq
                WHERE n < %d""".formatted(
                pick("n", Words.DEPARTMENTS), pick("(n DIV 25)", Words.DEPARTMENT_SUFFIXES), seed.categories());
    }

    private String productSql(long from, long count) {
        return """
                INSERT INTO product (id, sku, name, brand, category_id, price, rating, review_count, description,
                                     image, created_at)
                SELECT n + 1,
                       CONCAT('SKU', LPAD(n + 1, 9, '0')),
                       CONCAT(%s, ' ', %s, ' ', %s, ' ', LPAD(%s %% 10000, 4, '0')),
                       %s,
                       1 + FLOOR(%d * POW(%s, 1.5)),
                       ROUND(5 + POW(%s, 2) * 495, 2),
                       ROUND(3 + 2 * %s, 2),
                       FLOOR(2000 * POW(%s, 4)),
                       CONCAT(%s, ' ', %s, ' ', %s),
                       CONCAT('/img/p/', n %% 5000, '.jpg'),
                       TIMESTAMPADD(SECOND, -(%s %% %d), %s)
                FROM seed_seq
                WHERE n >= %d AND n < %d""".formatted(
                pick(hash("pa", "n"), Words.ADJECTIVES), pick(hash("pm", "n"), Words.MATERIALS),
                pick(hash("pn", "n"), Words.NOUNS), hash("px", "n"),
                pick(hash("pb", "n"), Words.BRANDS),
                seed.categories(), unit("pc", "n"),
                unit("pp", "n"),
                unit("pr", "n"),
                unit("pv", "n"),
                pick(hash("d1", "n"), Words.SENTENCES), pick(hash("d2", "n"), Words.SENTENCES),
                pick(hash("d3", "n"), Words.SENTENCES),
                hash("pt", "n"), TWO_YEARS_SECONDS, EPOCH,
                from, from + count);
    }

    private String customerSql(long from, long count) {
        return """
                INSERT INTO customer (id, email, name, city, tier, created_at)
                SELECT id,
                       CONCAT('user', id, '@example.com'),
                       CONCAT(%s, ' ', %s),
                       %s,
                       %s %% 4,
                       TIMESTAMPADD(SECOND, -(%s %% %d), %s)
                FROM (SELECT %d + n + 1 AS id FROM seed_seq WHERE n < %d) s""".formatted(
                pick(hash("cf", "id"), Words.FIRST_NAMES), pick(hash("cl", "id"), Words.LAST_NAMES),
                pick(hash("cc", "id"), Words.CITIES),
                hash("ct", "id"),
                hash("cd", "id"), TWO_YEARS_SECONDS, EPOCH,
                from, count);
    }

    /** Order ids rise with time, and a few customers place many of the orders. */
    private String ordersSql(long from, long count) {
        return """
                INSERT INTO orders (id, customer_id, status, total, item_count, created_at)
                SELECT id,
                       1 + FLOOR(%d * POW(%s, 2)),
                       %s %% 5,
                       ROUND((1 + (%s %% 5)) * (10 + (%s %% 19000) / 100), 2),
                       1 + (%s %% 5),
                       TIMESTAMPADD(SECOND, -FLOOR((%d - id) * %s), %s)
                FROM (SELECT %d + n + 1 AS id FROM seed_seq WHERE n < %d) s""".formatted(
                seed.customers(), unit("oc", "id"),
                hash("os", "id"),
                hash("on", "id"), hash("ot", "id"),
                hash("on", "id"),
                seed.orders(), Double.toString((double) TWO_YEARS_SECONDS / seed.orders()), EPOCH,
                from, count);
    }

    /** One to five lines per order. A small share of products receives most of the sales. */
    private String orderItemSql(long from, long count) {
        String key = "CONCAT(o.id, ':', l.d)";
        return """
                INSERT INTO order_item (order_id, line_no, product_id, qty, unit_price)
                SELECT o.id, l.d,
                       1 + FLOOR(%d * POW(%s, 3)),
                       1 + (%s %% 3),
                       ROUND(5 + POW(%s, 2) * 495, 2)
                FROM orders o
                JOIN seed_digit l ON l.d BETWEEN 1 AND o.item_count
                WHERE o.id > %d AND o.id <= %d""".formatted(
                seed.products(), unit("ip", key),
                hash("iq", key),
                unit("iu", key),
                from, from + count);
    }

    private String reviewSql(long from, long count) {
        return """
                INSERT INTO review (id, product_id, customer_id, rating, title, body, created_at)
                SELECT id,
                       1 + FLOOR(%d * POW(%s, 3)),
                       1 + (%s %% %d),
                       ELT(1 + (%s %% 10), 5, 5, 5, 5, 4, 4, 4, 3, 2, 1),
                       %s,
                       CONCAT(%s, ' ', %s),
                       TIMESTAMPADD(SECOND, -(%s %% %d), %s)
                FROM (SELECT %d + n + 1 AS id FROM seed_seq WHERE n < %d) s""".formatted(
                seed.products(), unit("rp", "id"),
                hash("rc", "id"), seed.customers(),
                hash("rr", "id"),
                pick(hash("rt", "id"), Words.REVIEW_TITLES),
                pick(hash("r1", "id"), Words.SENTENCES), pick(hash("r2", "id"), Words.SENTENCES),
                hash("rd", "id"), TWO_YEARS_SECONDS, EPOCH,
                from, count);
    }

    /**
     * Three cart lines per customer. The product of each line is a fixed function
     * of the customer and the line slot; the load test uses the same function, so
     * its cart writes update existing rows and the table does not grow.
     */
    private String cartSql(long from, long count) {
        return """
                INSERT IGNORE INTO cart_item (customer_id, product_id, qty, updated_at)
                SELECT c.id, 1 + ((c.id * 2654435761 + sl.d * 40503) %% %d), 1 + ((c.id + sl.d) %% 3), %s
                FROM customer c
                JOIN seed_digit sl ON sl.d < 3
                WHERE c.id > %d AND c.id <= %d""".formatted(seed.products(), EPOCH, from, from + count);
    }

    // ---- SQL expression helpers ---------------------------------------------------------

    /**
     * A 32-bit hash of the row key, independent for each salt. MD5 rather than CRC32:
     * CRC32 is linear, so two salts would give values that differ by a constant XOR
     * and every generated column would be correlated with every other.
     */
    private static String hash(String salt, String key) {
        return "CAST(CONV(SUBSTRING(MD5(CONCAT('" + salt + ":', " + key + ")), 1, 8), 16, 10) AS UNSIGNED)";
    }

    /** The hash scaled to [0, 1). */
    private static String unit(String salt, String key) {
        return "(" + hash(salt, key) + " / 4294967296)";
    }

    /** Picks one of the words by the value of an integer expression. */
    private static String pick(String intExpression, String[] words) {
        StringBuilder sql = new StringBuilder("ELT(1 + (").append(intExpression).append(" % ")
                .append(words.length).append(")");
        for (String word : words) {
            sql.append(", '").append(word.replace("'", "''")).append('\'');
        }
        return sql.append(')').toString();
    }
}
