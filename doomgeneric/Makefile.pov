# Copyright (C) 2026 RKO Consult UG (haftungsbeschraenkt)
# SPDX-License-Identifier: GPL-2.0-or-later
# cosmergon-pov: the window program (SDL2, no sound). Built on the device:
#   make -f Makefile.pov -j4
# Needs sdl2-config (SDL2 or sdl2-compat). No SDL2_mixer.

ifeq ($(V),1)
	VB=''
else
	VB=@
endif

CC?=gcc
CFLAGS+=-O2 -DPOV_NO_ERROR_DIALOG -DPOV_NO_WIPE -DPOV_VIEW_ONLY -MMD -MP $(shell sdl2-config --cflags)
LDFLAGS+=
LIBS+=-lm -lc $(shell sdl2-config --libs)

OBJDIR=build-pov
OUTPUT=cosmergon-pov

include pov_sources.mk
SRC_DOOM = $(POV_CORE) doomgeneric_pov.o
OBJS += $(addprefix $(OBJDIR)/, $(SRC_DOOM))

all: $(OUTPUT) capabilities

-include $(OBJS:.o=.d)

clean:
	rm -rf $(OBJDIR)
	rm -f $(OUTPUT) capabilities

# The words of the control lines this build accepts, next to the program: a bridge sends a newer line only
# when its word is listed (COSMERGON.md, "Capabilities"). tests/test_kinds.py holds the file and the code together.
capabilities: pov_capabilities.txt
	@echo [Writing $@]
	$(VB)cp pov_capabilities.txt $@

$(OUTPUT): $(OBJS)
	@echo [Linking $@]
	$(VB)$(CC) $(CFLAGS) $(LDFLAGS) $(OBJS) -o $(OUTPUT) $(LIBS)

$(OBJS): | $(OBJDIR)

$(OBJDIR):
	mkdir -p $(OBJDIR)

# Own code: strict warnings
$(OBJDIR)/doomgeneric_pov.o: doomgeneric_pov.c
	@echo [Compiling $<]
	$(VB)$(CC) $(CFLAGS) -Wall -Wextra -c $< -o $@

$(OBJDIR)/pov_stdin.o: pov_stdin.c
	@echo [Compiling $<]
	$(VB)$(CC) $(CFLAGS) -Wall -Wextra -c $< -o $@

$(OBJDIR)/pov_control.o: pov_control.c
	@echo [Compiling $<]
	$(VB)$(CC) $(CFLAGS) -Wall -Wextra -c $< -o $@

$(OBJDIR)/pov_sky.o: pov_sky.c
	@echo [Compiling $<]
	$(VB)$(CC) $(CFLAGS) -Wall -Wextra -c $< -o $@

$(OBJDIR)/%.o: %.c
	@echo [Compiling $<]
	$(VB)$(CC) $(CFLAGS) -c $< -o $@
