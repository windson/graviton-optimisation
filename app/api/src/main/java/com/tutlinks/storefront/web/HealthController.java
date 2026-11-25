package com.tutlinks.storefront.web;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Load balancer health check. It does not touch the database on purpose: a
 * database failover should not make the load balancer remove every API target.
 */
@RestController
class HealthController {

    @GetMapping("/api/healthz")
    String healthz() {
        return "ok";
    }
}
