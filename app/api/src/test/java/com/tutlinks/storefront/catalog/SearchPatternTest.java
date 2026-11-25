package com.tutlinks.storefront.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SearchPatternTest {

    @Test
    void appendsThePrefixWildcard() {
        assertThat(CatalogController.likePrefix("Compact Oak")).isEqualTo("Compact Oak%");
    }

    @Test
    void escapesWildcardsTypedByTheUser() {
        assertThat(CatalogController.likePrefix("50%_off\\")).isEqualTo("50\\%\\_off\\\\%");
    }
}
