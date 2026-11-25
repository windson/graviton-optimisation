-- Storefront schema. Index choices are explained next to each index because the
-- benchmark's database cost depends on them.

CREATE TABLE category (
  id            INT          NOT NULL,
  name          VARCHAR(64)  NOT NULL,
  slug          VARCHAR(64)  NOT NULL,
  product_count INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (id)
) ENGINE = InnoDB;

CREATE TABLE product (
  id           INT            NOT NULL AUTO_INCREMENT,
  sku          CHAR(12)       NOT NULL,
  name         VARCHAR(120)   NOT NULL,
  brand        VARCHAR(40)    NOT NULL,
  category_id  INT            NOT NULL,
  price        DECIMAL(10, 2) NOT NULL,
  rating       DECIMAL(3, 2)  NOT NULL,
  review_count INT            NOT NULL,
  description  VARCHAR(600)   NOT NULL,
  image        VARCHAR(120)   NOT NULL,
  created_at   DATETIME       NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_product_sku (sku),
  -- One index per listing sort order, so a page of results is read in index order.
  KEY idx_product_cat_rating (category_id, rating DESC, id),
  KEY idx_product_cat_price (category_id, price, id),
  KEY idx_product_cat_created (category_id, created_at DESC, id),
  -- Covers the brand and price facet queries of a listing page.
  KEY idx_product_cat_brand_price (category_id, brand, price),
  -- Covers prefix search ordered by popularity.
  KEY idx_product_name_reviews (name, review_count),
  KEY idx_product_created (created_at DESC, id)
) ENGINE = InnoDB;

CREATE TABLE inventory (
  product_id INT         NOT NULL,
  stock      INT         NOT NULL,
  updated_at DATETIME(3) NOT NULL,
  PRIMARY KEY (product_id)
) ENGINE = InnoDB;

CREATE TABLE customer (
  id         INT          NOT NULL,
  email      VARCHAR(120) NOT NULL,
  name       VARCHAR(80)  NOT NULL,
  city       VARCHAR(60)  NOT NULL,
  tier       TINYINT      NOT NULL,
  created_at DATETIME     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_customer_email (email)
) ENGINE = InnoDB;

CREATE TABLE orders (
  id          BIGINT         NOT NULL AUTO_INCREMENT,
  customer_id INT            NOT NULL,
  status      TINYINT        NOT NULL,
  total       DECIMAL(12, 2) NOT NULL,
  item_count  SMALLINT       NOT NULL,
  created_at  DATETIME(3)    NOT NULL,
  PRIMARY KEY (id),
  KEY idx_orders_customer (customer_id, created_at DESC, id DESC)
) ENGINE = InnoDB;

CREATE TABLE order_item (
  order_id   BIGINT         NOT NULL,
  line_no    TINYINT        NOT NULL,
  product_id INT            NOT NULL,
  qty        SMALLINT       NOT NULL,
  unit_price DECIMAL(10, 2) NOT NULL,
  PRIMARY KEY (order_id, line_no),
  -- Finds the most recent orders that contain a product ("bought together").
  KEY idx_order_item_product (product_id, order_id)
) ENGINE = InnoDB;

CREATE TABLE review (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  product_id  INT          NOT NULL,
  customer_id INT          NOT NULL,
  rating      TINYINT      NOT NULL,
  title       VARCHAR(120) NOT NULL,
  body        VARCHAR(500) NOT NULL,
  created_at  DATETIME     NOT NULL,
  PRIMARY KEY (id),
  KEY idx_review_product (product_id, created_at DESC, id DESC)
) ENGINE = InnoDB;

CREATE TABLE cart_item (
  customer_id INT         NOT NULL,
  product_id  INT         NOT NULL,
  qty         SMALLINT    NOT NULL,
  updated_at  DATETIME(3) NOT NULL,
  PRIMARY KEY (customer_id, product_id)
) ENGINE = InnoDB;

-- Records what the seed job loaded, so the job is idempotent and the load test
-- can read the data set dimensions instead of assuming them.
CREATE TABLE seed_meta (
  id            TINYINT     NOT NULL,
  version       VARCHAR(32) NOT NULL,
  categories    INT         NOT NULL,
  products      INT         NOT NULL,
  customers     INT         NOT NULL,
  orders        BIGINT      NOT NULL,
  max_order_id  BIGINT      NOT NULL,
  reviews       BIGINT      NOT NULL,
  completed_at  DATETIME    NOT NULL,
  PRIMARY KEY (id)
) ENGINE = InnoDB;
