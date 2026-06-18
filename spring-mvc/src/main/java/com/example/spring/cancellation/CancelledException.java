package com.example.spring.cancellation;

public class CancelledException extends RuntimeException {
    public CancelledException() {
        super("Request cancelled", null, true, false);
    }
}
