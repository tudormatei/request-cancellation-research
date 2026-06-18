package com.example.webflux.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
public class WebClientConfig {

    @Bean
    public WebClient downstreamWebClient(
            @Value("${DOWNSTREAM_URL:http://downstream:8090}") String downstreamUrl) {
        return WebClient.builder().baseUrl(downstreamUrl).build();
    }
}
