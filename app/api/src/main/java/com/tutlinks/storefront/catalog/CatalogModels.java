package com.tutlinks.storefront.catalog;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

/** Response shapes of the catalog endpoints. */
public final class CatalogModels {

    private CatalogModels() {
    }

    public record Category(int id, String name, String slug, int productCount) {
    }

    public record ProductSummary(int id, String name, String brand, BigDecimal price, BigDecimal rating,
                                 int reviewCount, String image) {
    }

    public record BrandFacet(String brand, int count, BigDecimal minPrice, BigDecimal maxPrice) {
    }

    public record PriceBand(int from, int to, int count) {
    }

    public record CatalogPage(int categoryId, String sort, String brand, int page, boolean hasNext,
                              List<ProductSummary> items, List<BrandFacet> brands, List<PriceBand> priceBands) {
    }

    public record Review(long id, int customerId, int rating, String title, String body, Instant createdAt) {
    }

    public record ProductDetail(int id, String sku, String name, String brand, int categoryId, String categoryName,
                                BigDecimal price, BigDecimal rating, int reviewCount, String description,
                                String image, int stock, List<Review> reviews, List<ProductSummary> alsoBought) {
    }

    public record SearchResult(String query, List<ProductSummary> items) {
    }

    public record Home(List<ProductSummary> newArrivals, List<FeaturedCategory> featured) {
    }

    public record FeaturedCategory(int categoryId, String categoryName, List<ProductSummary> topRated) {
    }

    public record DataSet(String version, int categories, int products, int customers, long orders,
                          long maxOrderId, long reviews) {
    }
}
