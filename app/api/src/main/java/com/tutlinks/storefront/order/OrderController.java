package com.tutlinks.storefront.order;

import com.tutlinks.storefront.order.OrderService.Confirmation;
import com.tutlinks.storefront.order.OrderService.PlaceOrder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
class OrderController {

    private final OrderService orders;

    OrderController(OrderService orders) {
        this.orders = orders;
    }

    @PostMapping("/orders")
    @ResponseStatus(HttpStatus.CREATED)
    Confirmation place(@RequestBody PlaceOrder order) {
        return orders.place(order);
    }
}
