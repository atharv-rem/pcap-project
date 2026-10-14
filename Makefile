# Top-level Makefile. Each member's targets live in mk/*.mk and append themselves to `all`.
.PHONY: all test clean

all:

-include mk/*.mk

build:
	mkdir -p build

clean:
	rm -rf build
