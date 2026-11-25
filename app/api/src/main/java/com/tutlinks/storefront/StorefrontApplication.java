package com.tutlinks.storefront;

import java.security.Security;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class StorefrontApplication {

    public static void main(String[] args) {
        // Aurora moves the writer endpoint to another instance on failover by changing DNS.
        // A short positive cache makes new connections follow that change within seconds.
        Security.setProperty("networkaddress.cache.ttl", "5");
        SpringApplication.run(StorefrontApplication.class, args);
    }
}
