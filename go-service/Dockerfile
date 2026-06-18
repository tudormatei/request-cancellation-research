FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /go-service .

FROM scratch
COPY --from=build /go-service /go-service
EXPOSE 8080
ENTRYPOINT ["/go-service"]
