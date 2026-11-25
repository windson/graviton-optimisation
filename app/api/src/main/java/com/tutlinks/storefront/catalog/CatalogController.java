package com.tutlinks.storefront.catalog;

import java.util.ArrayList;
import java.util.List;

import com.tutlinks.storefront.catalog.CatalogModels.CatalogPage;
import com.tutlinks.storefront.catalog.CatalogModels.Category;
import com.tutlinks.storefront.catalog.CatalogModels.DataSet;
import com.tutlinks.storefront.catalog.CatalogModels.FeaturedCategory;
import com.tutlinks.storefront.catalog.CatalogModels.Home;
import com.tutlinks.storefront.catalog.CatalogModels.ProductDetail;
import com.tutlinks.storefront.catalog.CatalogModels.ProductSummary;
import com.tutlinks.storefront.catalog.CatalogModels.SearchResult;
import com.tutlinks.storefront.catalog.CatalogRepository.Sort;
import com.tutlinks.storefront.config.CatalogProperties;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
class CatalogController {

    private static final int MAX_PAGE = 50;
    private static final int SEARCH_LIMIT = 24;
    private static final int FEATURED_CATEGORIES = 4;

    private final CatalogRepository repository;
    private final CategoryCache categories;
    private final int pageSize;

    CatalogController(CatalogRepository repository, CategoryCache categories, CatalogProperties properties) {
        this.repository = repository;
        this.categories = categories;
        this.pageSize = properties.pageSize();
    }

    @GetMapping("/categories")
    List<Category> categories() {
        return categories.all();
    }

    @GetMapping("/catalog")
    CatalogPage catalog(@RequestParam int category,
                        @RequestParam(defaultValue = "rating") String sort,
                        @RequestParam(required = false) String brand,
                        @RequestParam(defaultValue = "1") int page) {
        if (page < 1 || page > MAX_PAGE) {
            throw new IllegalArgumentException("page must be between 1 and " + MAX_PAGE);
        }
        Category found = categories.require(category);
        Sort order = Sort.parse(sort);
        String brandFilter = brand == null || brand.isBlank() ? null : brand;

        // One extra row tells the client whether another page exists without a COUNT query.
        List<ProductSummary> rows = repository.listing(found.id(), order, brandFilter, pageSize + 1,
                (page - 1) * pageSize);
        boolean hasNext = rows.size() > pageSize;
        List<ProductSummary> items = hasNext ? rows.subList(0, pageSize) : rows;

        return new CatalogPage(found.id(), order.name().toLowerCase(), brandFilter, page, hasNext, items,
                repository.brandFacets(found.id()), repository.priceBands(found.id()));
    }

    @GetMapping("/products/{id}")
    ProductDetail product(@PathVariable int id) {
        ProductDetail base = repository.product(id)
                .orElseThrow(() -> new NotFoundException("product " + id + " not found"));
        return new ProductDetail(base.id(), base.sku(), base.name(), base.brand(), base.categoryId(),
                base.categoryName(), base.price(), base.rating(), base.reviewCount(), base.description(),
                base.image(), base.stock(), repository.latestReviews(id, 5), repository.alsoBought(id, 8));
    }

    @GetMapping("/search")
    SearchResult search(@RequestParam String q) {
        String term = q.strip();
        if (term.length() < 2 || term.length() > 60) {
            throw new IllegalArgumentException("q must be between 2 and 60 characters");
        }
        return new SearchResult(term, repository.searchByNamePrefix(likePrefix(term), SEARCH_LIMIT));
    }

    @GetMapping("/home")
    Home home() {
        int total = categories.count();
        // The featured categories rotate once a minute so that every pod serves the same set.
        long minute = System.currentTimeMillis() / 60_000;
        List<FeaturedCategory> featured = new ArrayList<>(FEATURED_CATEGORIES);
        for (int slot = 0; slot < FEATURED_CATEGORIES && total > 0; slot++) {
            Category category = categories.all().get((int) ((minute * 7 + slot * 61L) % total));
            featured.add(new FeaturedCategory(category.id(), category.name(),
                    repository.listing(category.id(), Sort.RATING, null, 8, 0)));
        }
        return new Home(repository.newArrivals(16), featured);
    }

    @GetMapping("/meta")
    DataSet meta() {
        return repository.dataSet().orElseThrow(() -> new NotFoundException("data set not seeded"));
    }

    /** Escapes LIKE wildcards in user input and appends the prefix wildcard. */
    static String likePrefix(String term) {
        return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
    }
}
