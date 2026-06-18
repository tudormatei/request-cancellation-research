FROM eclipse-temurin:25-jdk AS build
WORKDIR /build
RUN apt-get update -qq && apt-get install -y -qq maven
COPY pom.xml .
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -q -DskipTests

FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=build /build/target/spring-webflux-0.0.1-SNAPSHOT.jar app.jar
ENTRYPOINT ["java", "-Djava.io.tmpdir=/tmp", "-jar", "app.jar"]
