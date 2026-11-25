package com.tutlinks.storefront;

import static org.hamcrest.Matchers.greaterThan;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Runs the whole API against a real MySQL server with a small generated data
 * set. Enabled in CI, where the build starts a MySQL 8.0 container and sets
 * IT_DB_HOST. The same seed statements populate the study's database.
 */
@SpringBootTest(properties = {
    "storefront.seed.enabled=true",
    "storefront.seed.version=it",
    "storefront.seed.categories=10",
    "storefront.seed.products=3000",
    "storefront.seed.customers=1000",
    "storefront.seed.orders=4000",
    "storefront.seed.reviews=3000",
    "storefront.db.socket-timeout-millis=0",
    "storefront.db.pool-size=8"})
@AutoConfigureMockMvc
@EnabledIfEnvironmentVariable(named = "IT_DB_HOST", matches = ".+")
class StorefrontApiIntegrationTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void reportsTheSeededDataSet() throws Exception {
        mvc.perform(get("/api/meta"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.products").value(3000))
                .andExpect(jsonPath("$.maxOrderId").value(4000));
        mvc.perform(get("/api/categories")).andExpect(status().isOk()).andExpect(jsonPath("$", hasSize(10)));
    }

    @Test
    void listsACategoryWithFacetsInEverySortOrder() throws Exception {
        for (String sort : new String[] {"rating", "price", "newest"}) {
            mvc.perform(get("/api/catalog").param("category", "1").param("sort", sort))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.items", hasSize(48)))
                    .andExpect(jsonPath("$.hasNext").value(true))
                    .andExpect(jsonPath("$.brands", not(hasSize(0))))
                    .andExpect(jsonPath("$.priceBands", not(hasSize(0))));
        }
        mvc.perform(get("/api/catalog").param("category", "1").param("brand", "Atlas"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.brand").value("Atlas"));
    }

    @Test
    void showsAProductWithReviewsAndRelatedProducts() throws Exception {
        // Product 1 is the best seller of the generated data set.
        mvc.perform(get("/api/products/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sku").value("SKU000000001"))
                .andExpect(jsonPath("$.stock", greaterThan(0)))
                .andExpect(jsonPath("$.reviews", not(hasSize(0))))
                .andExpect(jsonPath("$.alsoBought", not(hasSize(0))));
    }

    @Test
    void searchesByNamePrefixAndServesTheHomePage() throws Exception {
        mvc.perform(get("/api/search").param("q", "Compact"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items", not(hasSize(0))));
        mvc.perform(get("/api/home"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.newArrivals", hasSize(16)))
                .andExpect(jsonPath("$.featured", hasSize(4)));
    }

    @Test
    void readsAndUpdatesACartAndPlacesAnOrder() throws Exception {
        mvc.perform(get("/api/cart/5")).andExpect(status().isOk()).andExpect(jsonPath("$.lines", not(hasSize(0))));
        mvc.perform(put("/api/cart/5/items/17").contentType(MediaType.APPLICATION_JSON).content("{\"qty\":3}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.lines[?(@.productId == 17)].qty").value(3));

        mvc.perform(post("/api/orders").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"customerId\":5,\"items\":[{\"productId\":17,\"qty\":2},{\"productId\":3,\"qty\":1}]}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.orderId", greaterThan(4000)))
                .andExpect(jsonPath("$.lineCount").value(2));
        mvc.perform(get("/api/customers/5/orders"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].lines", hasSize(2)));
    }

    @Test
    void mapsExpectedFailuresToClientErrors() throws Exception {
        mvc.perform(get("/api/products/999999999")).andExpect(status().isNotFound());
        mvc.perform(get("/api/catalog").param("category", "1").param("sort", "random"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/catalog").param("category", "9999")).andExpect(status().isNotFound());
        mvc.perform(get("/api/search").param("q", "x")).andExpect(status().isBadRequest());
        mvc.perform(post("/api/orders").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"customerId\":5,\"items\":[]}"))
                .andExpect(status().isBadRequest());
    }
}
