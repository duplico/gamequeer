# Makefile for GQC workspace
#  Game-as-directory layout (gamequeer#420/#440): every game lives in its
#  own <name>/<name>.gq at this workspace root (a sibling of every other
#  top-level directory here -- assets/, tools/, build/, ...), not gathered
#  under a flat games/ directory. This file discovers that layout directly
#  (a top-level directory whose own name matches a .gq file inside it),
#  rather than delegating to `gqc update-makefile-local` / `gqc init-dir`,
#  which still only know the old flat games/*.gq convention as of this
#  writing (gqc's own Makefile-generation is tracked separately from this
#  layout migration -- see gqc/src/gqc/migrate.py's module docstring;
#  gq-games's own top-level Makefile took the same approach for the same
#  reason, gq-games#54). Concretely: do NOT run `gqc init-dir --force` in
#  this workspace -- it will overwrite this file with that stale
#  flat-layout template.
#
#  So, unlike a freshly-scaffolded `gqc new`/`gqc init-dir` workspace's
#  Makefile, this one is hand-maintained, not GQC-generated -- edit it
#  freely.

BASE_DIR := $(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))

ifndef GQC_CMD
# uv (https://docs.astral.sh/uv/) runs gqc straight out of this repo's own
# gqc/ checkout -- no install step, no venv to activate, no PATH to manage.
# examples/ knows exactly where that checkout lives relative to itself
# (a sibling directory), which a workspace outside this repo wouldn't --
# see gqc/src/gqc/makefile_src.py's GQC_CMD default/comment for that case.
# Override this if you'd rather invoke a different gqc, e.g. `GQC_CMD :=
# gqc` after `uv tool install ./gqc`.
GQC_CMD := uv run --project $(BASE_DIR)/../gqc -m gqc
endif

# Every top-level directory name that contains its own matching entry
# file (<name>/<name>.gq) -- i.e. every migrated game. A top-level
# directory that ISN'T a game (assets/, tools/, build/, ...) simply has no
# same-named .gq inside it and is silently skipped.
CANDIDATE_DIRS := $(patsubst $(BASE_DIR)/%/,%,$(wildcard $(BASE_DIR)/*/))
GAME_NAMES := $(foreach d,$(CANDIDATE_DIRS),$(if $(wildcard $(BASE_DIR)/$(d)/$(d).gq),$(d)))
GAME_OUTS := $(foreach g,$(GAME_NAMES),$(BASE_DIR)/build/$(g)/$(g).gqgame)

.PHONY: all clean
.DEFAULT_GOAL := all

all: $(GAME_OUTS)

# One static-pattern-style rule per discovered game: build/<name>/<name>.gqgame
# depends on (only) <name>/<name>.gq -- matching gqc's own
# update-makefile-local's prerequisite scope, which never tracked a
# game's assets/ subtree either (only its entry .gq file). If you're
# iterating on assets without touching the .gq source itself, `make
# clean` (or delete that game's build/<name>/ dir) to force a rebuild.
define GAME_RULE
$(BASE_DIR)/build/$(1)/$(1).gqgame: $(BASE_DIR)/$(1)/$(1).gq
	$$(GQC_CMD) compile -o $(BASE_DIR)/build/$(1) $$<
endef
$(foreach g,$(GAME_NAMES),$(eval $(call GAME_RULE,$(g))))

clean:
	-rm -rf build/*
