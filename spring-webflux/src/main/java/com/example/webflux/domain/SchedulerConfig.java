package com.example.webflux.domain;

import reactor.core.scheduler.Scheduler;
import reactor.core.scheduler.Schedulers;

public final class SchedulerConfig {

    public static final String NAME =
        System.getenv().getOrDefault("REACTOR_SCHEDULER", "boundedElastic");

    public static final Scheduler CPU = switch (NAME) {
        case "immediate" -> Schedulers.immediate();
        default -> Schedulers.boundedElastic();
    };

    private SchedulerConfig() {}
}
