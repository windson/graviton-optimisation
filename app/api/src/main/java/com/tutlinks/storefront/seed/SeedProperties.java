package com.tutlinks.storefront.seed;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Size of the generated data set. The defaults are the values used in the study. */
@ConfigurationProperties("storefront.seed")
public record SeedProperties(
        @DefaultValue("false") boolean enabled,
        @DefaultValue("v1") String version,
        @DefaultValue("500") int categories,
        @DefaultValue("1000000") int products,
        @DefaultValue("2000000") int customers,
        @DefaultValue("8000000") long orders,
        @DefaultValue("5000000") long reviews,
        @DefaultValue("6") int parallelism) {

    public SeedProperties {
        if (categories < 1 || categories > 500) {
            throw new IllegalArgumentException("categories must be between 1 and 500");
        }
        if (products < 1 || products > 1_000_000) {
            throw new IllegalArgumentException("products must be between 1 and 1,000,000");
        }
        if (customers < 1 || orders < 1 || reviews < 1 || parallelism < 1) {
            throw new IllegalArgumentException("customers, orders, reviews and parallelism must be positive");
        }
    }
}
