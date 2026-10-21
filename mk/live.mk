# [M3] raylib live demo.
# raylib flags come from pkg-config when it knows raylib, else the usual Linux libraries.
# Override on the command line if needed: make live RAYLIB_LIBS="-L/opt/raylib/lib -lraylib ..."
LIVE_CFLAGS   := -O2 -std=c11 -Wall -Wextra
LIVE_SRCS     := src/live.c src/sim.c src/grid_io.c
RAYLIB_CFLAGS ?= $(shell pkg-config --cflags raylib 2>/dev/null)
RAYLIB_LIBS   ?= $(shell pkg-config --libs raylib 2>/dev/null || echo -lraylib -lGL -lm -lpthread -ldl -lrt -lX11)
RAYLIB_FOUND  := $(shell $(CC) $(RAYLIB_CFLAGS) -E -include raylib.h -x c /dev/null >/dev/null 2>&1 && echo yes)
RAYLIB_HINT   := raylib not found. Ubuntu 24.04 has no libraylib-dev package: build raylib from source (see docs/notes_M3.md) or pass RAYLIB_CFLAGS / RAYLIB_LIBS

.PHONY: live live-missing
# `make all` still works without raylib: it only warns. `make live` fails with the hint.
ifeq ($(RAYLIB_FOUND),yes)
all: live
else
all: live-missing
endif
live: build/live

live-missing:
	@echo "WARNING: skipping build/live: $(RAYLIB_HINT)"

build/live: $(LIVE_SRCS) src/sim.h | build
ifneq ($(RAYLIB_FOUND),yes)
	@echo "make live: $(RAYLIB_HINT)"; exit 1
endif
	$(CC) $(LIVE_CFLAGS) $(RAYLIB_CFLAGS) -Isrc -o $@ $(LIVE_SRCS) $(RAYLIB_LIBS) -lm
