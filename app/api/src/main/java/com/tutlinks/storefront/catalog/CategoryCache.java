package com.tutlinks.storefront.catalog;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import com.tutlinks.storefront.catalog.CatalogModels.Category;
import com.tutlinks.storefront.config.CatalogProperties;
import org.springframework.stereotype.Component;

/**
 * Categories change rarely and are needed by almost every request, so they are
 * held in memory and reloaded when the snapshot is older than the configured TTL.
 */
@Component
public class CategoryCache {

    private record Snapshot(List<Category> all, Map<Integer, Category> byId, long loadedAtNanos) {
    }

    private final CatalogRepository repository;
    private final long ttlNanos;
    private volatile Snapshot snapshot;

    CategoryCache(CatalogRepository repository, CatalogProperties properties) {
        this.repository = repository;
        this.ttlNanos = properties.categoryCacheTtl().toNanos();
    }

    public List<Category> all() {
        return current().all();
    }

    public Category require(int id) {
        Category category = current().byId().get(id);
        if (category == null) {
            throw new NotFoundException("category " + id + " not found");
        }
        return category;
    }

    public int count() {
        return current().all().size();
    }

    private Snapshot current() {
        Snapshot now = snapshot;
        if (now == null || System.nanoTime() - now.loadedAtNanos() > ttlNanos) {
            // Concurrent reloads are harmless: each produces an equivalent snapshot.
            List<Category> all = List.copyOf(repository.categories());
            Map<Integer, Category> byId = all.stream().collect(Collectors.toMap(Category::id, Function.identity()));
            now = new Snapshot(all, byId, System.nanoTime());
            snapshot = now;
        }
        return now;
    }
}
