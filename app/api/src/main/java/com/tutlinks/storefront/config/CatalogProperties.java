package com.tutlinks.storefront.config;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties("storefront.catalog")
public record CatalogProperties(
        @DefaultValue("48") int pageSize,
        @DefaultValue("60s") Duration categoryCacheTtl) {
}
