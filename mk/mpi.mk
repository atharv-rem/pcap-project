# [M2] MPI engine.
MPICC      ?= mpicc
MPI_CFLAGS := -O2 -std=c11 -Wall -Wextra
MPI_SRCS   := src/mpi_main.c src/scenarios.c src/sim.c src/grid_io.c
MPI_HDRS   := src/sim.h src/scenarios.h

.PHONY: mpi scenarios_check
all: mpi
mpi: build/flood_mpi

build/flood_mpi: $(MPI_SRCS) $(MPI_HDRS) | build
	$(MPICC) $(MPI_CFLAGS) -Isrc -o $@ $(MPI_SRCS) -lm

# Tiny check of the scenario list (no MPI needed): build/scenarios_check 4 3 10 60 1 4 12
scenarios_check: build/scenarios_check

build/scenarios_check: src/scenarios.c $(MPI_HDRS) | build
	$(CC) $(MPI_CFLAGS) -DSCENARIOS_CHECK_MAIN -Isrc -o $@ src/scenarios.c -lm
