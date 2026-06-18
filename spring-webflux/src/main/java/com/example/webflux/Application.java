package com.example.webflux;

import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import io.r2dbc.spi.ConnectionFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;

@SpringBootApplication
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    ApplicationRunner ghostWriteTableInit(DatabaseClient databaseClient) {
        return (ApplicationArguments args) -> {
            databaseClient
                    .sql("CREATE TABLE IF NOT EXISTS ghost_writes " +
                         "(req_id UUID PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW())")
                    .then()
                    .block();
            databaseClient
                    .sql("CREATE TABLE IF NOT EXISTS txn_writes " +
                         "(req_id UUID NOT NULL, step INT NOT NULL, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(), " +
                         "PRIMARY KEY(req_id, step))")
                    .then()
                    .block();
            System.out.println("ghost_writes table ready");
            System.out.println("reactor_scheduler=" + com.example.webflux.domain.SchedulerConfig.NAME +
                    " yield_interval_ms=" +
                    System.getenv().getOrDefault("YIELD_INTERVAL_MS", "100"));
        };
    }

    @Bean
    TransactionalOperator transactionalOperator(ConnectionFactory connectionFactory) {
        return TransactionalOperator.create(new R2dbcTransactionManager(connectionFactory));
    }

    @Bean(destroyMethod = "shutdown")
    ManagedChannel downstreamGrpcChannel() {
        String target = System.getenv().getOrDefault("DOWNSTREAM_GRPC_URL", "downstream:50051");
        return ManagedChannelBuilder.forTarget(target).usePlaintext().build();
    }
}
