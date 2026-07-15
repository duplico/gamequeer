project_name=gamequeer
BASE_DIR:=$(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))
IMAGES:=$(shell docker images $(project_name)-builder -a -q)

CURRENT_UID := $(shell id -u)
CURRENT_GID := $(shell id -g)

export CURRENT_UID
export CURRENT_GID

.PHONY: clean-builder clean-code clean all builder-run builder-rebuild gqc gamequeer gq-game-language golden-fixture test-headless
.DEFAULT_GOAL := all

DOCKER_CMD := docker run -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$(DISPLAY) -h $(HOSTNAME) --rm -it --workdir /workspaces/gamequeer -v $(PWD):/workspaces/gamequeer --user $(CURRENT_UID):$(CURRENT_GID) $(project_name)-builder:latest

builder-build: builder.Dockerfile requirements.txt gq-game-language/install-langium-deps.sh 
	docker build -f builder.Dockerfile -t $(project_name)-builder:latest .
	@touch $@

builder-rebuild:
	docker build --no-cache -f builder.Dockerfile -t $(project_name)-builder:latest .
	@touch builder-build

builder-run:
	$(DOCKER_CMD) /bin/bash

### Build targets in subdirectories

gamequeer/build/gamequeer: builder-build gamequeer/src/bytecode.c gamequeer/src/gamequeer.c gamequeer/src/HAL.c gamequeer/src/leds.c gamequeer/src/main.c gamequeer/src/menu.c gamequeer/src/oled.c
	$(DOCKER_CMD) /bin/bash -c "cd gamequeer && cmake -B build && cmake --build build"

gqc/dist/gqc-0.0.1.tar.gz gqc/dist/gqc-0.0.1-py3-none-any.whl: builder-build
	$(DOCKER_CMD) /bin/bash -c "cd gqc && python -m build"

gq-game-language/gq-game-language-0.0.1.vsix: builder-build gq-game-language/src/language/game-queer-game-language.langium
	$(DOCKER_CMD) /bin/bash -c "cd gq-game-language && npm install langium && npm run langium:generate && npm run build && vsce package --allow-missing-repository"

### Build targets in root build directory

build/gamequeer: gamequeer/build/gamequeer
	mkdir -p build
	cp $(BASE_DIR)/gamequeer/build/gamequeer $@

build/gqc-0.0.1.tar.gz: gqc/dist/gqc-0.0.1.tar.gz
	mkdir -p build
	cp $(BASE_DIR)/gqc/dist/gqc-0.0.1.tar.gz $@

build/gqc-0.0.1-py3-none-any.whl: gqc/dist/gqc-0.0.1-py3-none-any.whl
	mkdir -p build
	cp $(BASE_DIR)/gqc/dist/gqc-0.0.1-py3-none-any.whl $@

build/gq-game-language.vsix: gq-game-language/gq-game-language-0.0.1.vsix
	mkdir -p build
	cp $(BASE_DIR)/gq-game-language/gq-game-language-0.0.1.vsix $@

### Pseudo-targets for the toolchain:

gqc: build/gqc-0.0.1.tar.gz build/gqc-0.0.1-py3-none-any.whl

gamequeer: build/gamequeer

gq-game-language: build/gq-game-language.vsix

### Headless golden-test targets

DOCKER_CMD_NIT := docker run --rm --workdir /workspaces/gamequeer -v $(PWD):/workspaces/gamequeer --user $(CURRENT_UID):$(CURRENT_GID) $(project_name)-builder:latest

# Compile the golden-test fixtures. The output .gqgame carts under
# gamequeer/tests/golden/ are committed to the repo.
#  - hello.gq: no ffmpeg needed; no GIF/image assets.
#  - mask_encoding_a.gq / mask_encoding_b.gq: masked-sprite (fganim/fgmask)
#    fixtures with PNG assets under gamequeer/tests/golden/assets/animations/;
#    gqc resolves animation sources relative to CWD, so these must be
#    compiled from gamequeer/tests/golden itself (see #262/#272 golden-test
#    follow-up).
#  - redundant_write.gq: SETVAR redundant-refresh regression fixture (#265/
#    PR#274); no ffmpeg/image assets needed either.
#  - anim_advance.gq: multi-frame animation cache-invalidation regression
#    fixture (#264/PR#282), using bwcircles.gif under
#    gamequeer/tests/golden/assets/animations/ (same ffmpeg/GIF pipeline as
#    mask_encoding_{a,b}.gq, so compiled from gamequeer/tests/golden too).
golden-fixture: builder-build gamequeer/tests/golden/hello.gq gamequeer/tests/golden/mask_encoding_a.gq gamequeer/tests/golden/mask_encoding_b.gq gamequeer/tests/golden/mask_encoding_c.gq gamequeer/tests/golden/redundant_write.gq gamequeer/tests/golden/anim_advance.gq gamequeer/tests/golden/rowmajor_byte_blit.gq gamequeer/tests/golden/edge_coverage.gq
	$(DOCKER_CMD_NIT) /bin/bash -c "PYTHONPATH=gqc/src python -m gqc compile --no-mem-map -o gamequeer/tests/golden gamequeer/tests/golden/hello.gq && \
		PYTHONPATH=gqc/src python -m gqc compile --no-mem-map -o gamequeer/tests/golden gamequeer/tests/golden/redundant_write.gq && \
		cd gamequeer/tests/golden && \
		PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc compile --no-mem-map -o . mask_encoding_a.gq && \
		PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc compile --no-mem-map -o . mask_encoding_b.gq && \
		PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc compile --no-mem-map -o . mask_encoding_c.gq && \
		PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc compile --no-mem-map -o . anim_advance.gq && \
		PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc compile --no-mem-map -o . rowmajor_byte_blit.gq && \
		PYTHONPATH=/workspaces/gamequeer/gqc/src python -m gqc compile --no-mem-map -o . edge_coverage.gq && \
		rm -rf build"

# Build the headless emulator and run the golden framebuffer test.
test-headless: builder-build
	$(DOCKER_CMD_NIT) /bin/bash -c "cd gamequeer && cmake -B build-headless -DGQ_HEADLESS=ON && cmake --build build-headless && cd build-headless && ctest --verbose"

### Important meta targets

all: gqc gamequeer gq-game-language

clean-builder:
ifeq ($(IMAGES),)
	@echo "No images to remove"
else
	-docker rmi $(IMAGES)
endif

clean-code:
	rm -rf build/
	rm -f builder-build
	rm -rf gamequeer/build/
	rm -rf gqc/dist/
	rm -f gq-game-language/gq-game-language-0.0.1.vsix
	rm -rf gq-game-language/out/ gq-game-language/syntaxes/



clean: clean-code clean-builder
