# Request Cancellation in Web Application Frameworks

Bachelor's thesis (Computer Science, University of Twente) by **Tudor Alexandru Matei**, supervised by dr. L. Ferreira Pires.

## What this studies

When a client disconnects mid-request (closed tab, navigation, lost connection), does the server stop working — or does it keep burning CPU and database resources for a response nobody will receive?

This project empirically compares how three backend frameworks detect, propagate, and act on client-disconnect signals, and quantifies the cost when they don't.

**Main research question:** How do the request cancellation architectures of web application frameworks differ in their ability to detect, propagate, and terminate a client request, concerning reliability, resource utilization, and system state correctness?

- **RQ1 — Detection:** How quickly and reliably does each framework detect a client disconnect under load?
- **RQ2 — Propagation:** How does the cancellation signal propagate through system layers (application code, database, outbound services) under each framework's idiomatic implementation?
- **RQ3 — Consequences:** What are the behavioral consequences of incomplete cancellation propagation, in terms of resource occupancy and system state?

## Taxonomy

Frameworks are classified by **cancellation signal source** — the route a disconnect takes to reach running application code — not by their concurrency model (those are orthogonal). This yields three mutually exclusive architectures:

| Architecture | Signal source | Detection | Propagation | Representative |
|---|---|---|---|---|
| **Passive** | Write-triggered socket error only | None (by specification) | N/A | Spring MVC |
| **Cooperative** | Explicit token passed through the call stack | Automatic | Manual (developer must thread + poll the token) | ASP.NET Core |
| **Reactive** | Subscription cancellation propagates through the operator graph | Automatic | Automatic (structural) | Spring WebFlux |

A disconnect either reaches application code or not (passive vs. the rest); when it does, propagation is either manually threaded (cooperative) or fully automatic (reactive). This decision tree yields exactly three classes by construction.

## Frameworks and roles

| Framework | Architecture | Role |
|---|---|---|
| Spring MVC | Passive | Qualitative baseline (0% detection on non-streaming endpoints, by Servlet spec) |
| ASP.NET Core | Cooperative | Quantitative subject |
| Spring WebFlux | Reactive | Quantitative subject |

The quantitative comparison (ASP.NET vs. WebFlux) crosses a C#/Java language boundary — an acknowledged confound, mitigated by using language-independent metrics (proportions, dimensionless ratios) wherever possible, and a load-dependence argument where raw latencies are reported (a language-speed offset is constant across load and cannot explain load-dependent trends).

## Repository layout

```
aspnet/             ASP.NET Core implementation (C#, Kestrel + CancellationToken, Npgsql)
spring-mvc/         Spring MVC implementation (Java, Servlet async, passive baseline)
spring-webflux/     Spring WebFlux implementation (Java, Project Reactor, R2DBC)
go-service/         Go service used as a second cooperative-architecture data point (context.Context)
downstream/         Mock downstream service (HTTP/1.1 + gRPC) used to test outbound propagation
docker-compose.yml  Full containerized stack: Postgres + the four framework services
.env                Per-service port/CPU/memory configuration for docker-compose

scripts/sq1/ sq2/ sq3/   Shell drivers that run the experiments against the running stack
tests/sq1/ sq2/ sq3/     Python collectors (*_collect.py) and analysers (*_analyse.py / *_plot.py)
experiments/sq1/ sq2/ sq3/  Raw CSV results, logs, and generated figures per sub-question
```

Each framework implements the same three-layer design (Controller → Service → Repository) so that implementation differences are isolated to the layer that actually differs (e.g. the database driver).

## Experiments

| RQ | Experiment | Scenario(s) | What it measures |
|---|---|---|---|
| RQ1 (reliability) | E1a | CPU loop, async | Cancellation rate vs. concurrency; the cooperative-architecture detection cliff |
| RQ1 (latency) | E1b | CPU loop, async | Detection latency `L1` and what governs it (thread-pool saturation, yield interval `K`) |
| RQ2 (propagation) | E2 | DB query, outbound HTTP/gRPC | Whether the signal crosses connection-close, in-band, and out-of-band abort boundaries |
| RQ3 (resources) | E3 | DB query under load | Connection hold time `H` and maximum sustainable request rate vs. pool size |
| RQ3 (state) | E4 | Single write, two-step write | Ghost-write rate, torn writes, and the effect of transaction boundaries |

Cancellation is induced, not simulated: the client embeds its planned disconnect time as a query parameter, issues the request, and closes the TCP connection at that wall-clock time, so latency is measured against a client-supplied reference rather than network round-trip noise. All services log to stdout using an identical event schema (request arrival, disconnect detected, layer reached, query completed/aborted) so cross-framework differences reflect framework behavior, not measurement artifacts.

## Key findings

- **Detection (RQ1):** Reactive detection is load-invariant. Cooperative detection matches it when a worker thread is free (~1 ms), falls to a slow branch (≈2·`K`) under saturation, and beyond a predictable cliff `N_safe ≈ 5499 · (C/K)^0.880` becomes unreliable. Passive detects nothing, by specification.
- **Propagation (RQ2):** Both cooperative and reactive architectures propagate across connection-close and in-band (gRPC) abort. Only cooperative propagates across *out-of-band* abort (PostgreSQL `CancelRequest`) — this is a structural limitation of reactive pipelined/backpressured drivers (R2DBC), not an implementation defect. Cooperative cancellation is a *completion event* (verifiable: the query has actually stopped); reactive cancellation is a *notification* decoupled from I/O state (not verifiable from the application).
- **Consequences (RQ3):** Incomplete cancellation costs resource-occupancy time following Little's law (`X_max = P / E[S]`), independent of database specifics — it generalizes to any bounded pool. Data-state consistency is governed by the **transaction boundary**, not the cancellation architecture: a single write produces a ghost-write under reactive (always) and conditionally under cooperative; an un-transacted multi-step write is left torn under both; wrapping it in a transaction makes both roll back safely. Spring MVC, by never reacting to the disconnect, is the only architecture that always leaves consistent data — honoring cancellation without a transaction is worse for integrity than ignoring it.

## Running the experiments

1. Copy/adjust `.env` for the target machine (CPU pinning, memory limits, ports).
2. Start the stack for the framework(s) under test (`postgres` always runs; pick the services needed via profiles):
   ```
   docker compose --profile aspnet --profile spring-webflux --profile downstream up -d
   ```
   (profiles: `aspnet`, `spring-mvc`, `spring-webflux`, `go`, `downstream`)
3. Run the relevant shell driver, e.g.:
   ```
   ./scripts/sq1/e1a_run.sh
   ./scripts/sq3/e3_run.sh
   ```
4. Analyse the collected CSVs:
   ```
   python tests/sq1/e1a_analyse.py
   ```

Results land in `experiments/<sq>/<experiment>/` as CSVs, with logs and generated figures alongside.

## Limitations

- Controlled Docker environment, not production.
- Cross-language (C#/Java) comparison between ASP.NET Core and Spring WebFlux is an acknowledged confound, mitigated via normalized/dimensionless metrics rather than raw timing comparisons.
- Only PostgreSQL was tested for the out-of-band abort protocol gap; the result is argued to generalize to the abort protocol class, not re-tested against other databases.
- The reactive out-of-band cancellation gap was confirmed against a single driver (R2DBC); generalization rests on an architectural argument rather than testing additional drivers.
