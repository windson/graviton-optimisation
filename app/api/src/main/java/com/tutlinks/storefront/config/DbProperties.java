package com.tutlinks.storefront.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * Database connection settings. Credentials come either from {@code secretArn}
 * (AWS Secrets Manager, used in the cluster) or from {@code username} and
 * {@code password} (used by tests and local runs).
 */
@ConfigurationProperties("storefront.db")
public record DbProperties(
        @DefaultValue("localhost") String host,
        @DefaultValue("3306") int port,
        @DefaultValue("storefront") String name,
        @DefaultValue("") String secretArn,
        @DefaultValue("") String username,
        @DefaultValue("") String password,
        @DefaultValue("24") int poolSize,
        @DefaultValue("REQUIRED") String sslMode,
        @DefaultValue("30000") int socketTimeoutMillis) {

    public String jdbcUrl() {
        // Driver settings recommended by HikariCP for MySQL, plus timeouts so that a
        // connection to a failed-over instance is abandoned instead of hanging.
        return "jdbc:mysql://" + host + ":" + port + "/" + name
                + "?sslMode=" + sslMode
                + "&connectTimeout=3000"
                + "&socketTimeout=" + socketTimeoutMillis
                + "&tcpKeepAlive=true"
                + "&connectionTimeZone=UTC"
                + "&cachePrepStmts=true"
                + "&prepStmtCacheSize=250"
                + "&prepStmtCacheSqlLimit=2048"
                + "&useServerPrepStmts=true"
                + "&useLocalSessionState=true"
                + "&rewriteBatchedStatements=true"
                + "&cacheResultSetMetadata=true"
                + "&cacheServerConfiguration=true"
                + "&elideSetAutoCommits=true"
                + "&maintainTimeStats=false";
    }
}
