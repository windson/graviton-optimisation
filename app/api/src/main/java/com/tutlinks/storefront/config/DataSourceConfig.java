package com.tutlinks.storefront.config;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Configuration(proxyBeanMethods = false)
class DataSourceConfig {

    private static final Logger log = LoggerFactory.getLogger(DataSourceConfig.class);

    private record Credentials(String username, String password) {
    }

    @Bean(destroyMethod = "close")
    HikariDataSource dataSource(DbProperties db) {
        Credentials credentials = db.secretArn().isBlank()
                ? new Credentials(db.username(), db.password())
                : fromSecretsManager(db.secretArn());

        HikariConfig config = new HikariConfig();
        config.setPoolName("storefront");
        config.setJdbcUrl(db.jdbcUrl());
        config.setUsername(credentials.username());
        config.setPassword(credentials.password());
        // A fixed-size pool keeps the number of database connections constant during a test.
        config.setMaximumPoolSize(db.poolSize());
        config.setMinimumIdle(db.poolSize());
        // Fail a request quickly when the pool is exhausted instead of queueing without bound.
        config.setConnectionTimeout(3_000);
        config.setValidationTimeout(2_000);
        config.setMaxLifetime(600_000);
        log.info("database pool: host={} database={} size={}", db.host(), db.name(), db.poolSize());
        return new HikariDataSource(config);
    }

    private static Credentials fromSecretsManager(String secretArn) {
        try (SecretsManagerClient client = SecretsManagerClient.builder()
                .httpClient(UrlConnectionHttpClient.create())
                .build()) {
            String secret = client.getSecretValue(request -> request.secretId(secretArn)).secretString();
            JsonNode json = JsonMapper.builder().build().readTree(secret);
            return new Credentials(json.get("username").asString(), json.get("password").asString());
        }
    }
}
