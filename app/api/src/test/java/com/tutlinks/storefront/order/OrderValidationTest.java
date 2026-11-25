package com.tutlinks.storefront.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;

import java.util.List;
import java.util.Map;

import com.tutlinks.storefront.order.OrderService.Item;
import com.tutlinks.storefront.order.OrderService.PlaceOrder;
import org.junit.jupiter.api.Test;

class OrderValidationTest {

    @Test
    void mergesRepeatedProductsAndSortsLinesByProduct() {
        Map<Integer, Integer> lines = OrderService.validate(
                new PlaceOrder(7, List.of(new Item(30, 1), new Item(10, 2), new Item(30, 4))));

        assertThat(lines).containsExactly(Map.entry(10, 2), Map.entry(30, 5));
    }

    @Test
    void rejectsEmptyOrders() {
        assertThatIllegalArgumentException().isThrownBy(() -> OrderService.validate(new PlaceOrder(7, List.of())));
        assertThatIllegalArgumentException().isThrownBy(() -> OrderService.validate(new PlaceOrder(7, null)));
    }

    @Test
    void rejectsQuantitiesAboveTheLimitAfterMerging() {
        assertThatIllegalArgumentException().isThrownBy(() -> OrderService.validate(
                new PlaceOrder(7, List.of(new Item(1, 15), new Item(1, 15)))));
    }

    @Test
    void rejectsNonPositiveIdentifiers() {
        assertThatIllegalArgumentException().isThrownBy(() -> OrderService.validate(
                new PlaceOrder(0, List.of(new Item(1, 1)))));
        assertThatIllegalArgumentException().isThrownBy(() -> OrderService.validate(
                new PlaceOrder(7, List.of(new Item(0, 1)))));
    }

    @Test
    void rejectsMoreLinesThanTheLimit() {
        List<Item> items = java.util.stream.IntStream.rangeClosed(1, OrderService.MAX_LINES + 1)
                .mapToObj(id -> new Item(id, 1))
                .toList();

        assertThatIllegalArgumentException().isThrownBy(() -> OrderService.validate(new PlaceOrder(7, items)));
    }
}
