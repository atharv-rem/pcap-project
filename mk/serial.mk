# [M1] serial runner and simulation tests.
SERIAL_CFLAGS := -O2 -std=c11 -Wall -Wextra
SIM_SRCS      := src/sim.c src/grid_io.c

.PHONY: serial
all: serial
serial: build/flood_serial

build/flood_serial: src/main_serial.c $(SIM_SRCS) src/sim.h | build
	$(CC) $(SERIAL_CFLAGS) -Isrc -o $@ src/main_serial.c $(SIM_SRCS) -lm

build/test_sim: tests/test_sim.c $(SIM_SRCS) src/sim.h | build
	$(CC) $(SERIAL_CFLAGS) -Isrc -o $@ tests/test_sim.c $(SIM_SRCS) -lm

test: build/test_sim
	./build/test_sim
