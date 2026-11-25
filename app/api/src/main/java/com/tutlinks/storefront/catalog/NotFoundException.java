package com.tutlinks.storefront.catalog;

/** Mapped to HTTP 404 by {@code ApiExceptionHandler}. */
public class NotFoundException extends RuntimeException {

    public NotFoundException(String message) {
        super(message);
    }
}
