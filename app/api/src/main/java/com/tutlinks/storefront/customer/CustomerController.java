package com.tutlinks.storefront.customer;

import java.util.List;

import com.tutlinks.storefront.catalog.NotFoundException;
import com.tutlinks.storefront.customer.CustomerRepository.Cart;
import com.tutlinks.storefront.customer.CustomerRepository.OrderSummary;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
class CustomerController {

    record CartItemRequest(int qty) {
    }

    private static final int MAX_QTY = 20;

    private final CustomerRepository repository;

    CustomerController(CustomerRepository repository) {
        this.repository = repository;
    }

    @GetMapping("/customers/{customerId}/orders")
    List<OrderSummary> orders(@PathVariable int customerId) {
        return repository.recentOrders(customerId, 10);
    }

    @GetMapping("/cart/{customerId}")
    Cart cart(@PathVariable int customerId) {
        return repository.cart(customerId);
    }

    @PutMapping("/cart/{customerId}/items/{productId}")
    Cart putCartItem(@PathVariable int customerId, @PathVariable int productId,
                     @RequestBody CartItemRequest request) {
        if (request.qty() < 0 || request.qty() > MAX_QTY) {
            throw new IllegalArgumentException("qty must be between 0 and " + MAX_QTY);
        }
        if (request.qty() > 0 && !repository.productExists(productId)) {
            throw new NotFoundException("product " + productId + " not found");
        }
        repository.putCartItem(customerId, productId, request.qty());
        return repository.cart(customerId);
    }
}
