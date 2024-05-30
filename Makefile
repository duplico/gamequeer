project_name=gamequeer
BASE_DIR:=$(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))
IMAGES:=$(shell docker images $(project_name)-builder -a -q)

CURRENT_UID := $(shell id -u)
CURRENT_GID := $(shell id -g)

export CURRENT_UID
export CURRENT_GID

.PHONY: clean-builder clean-code clean all builder-run builder-rebuild gqc gamequeer gq-game-language
.DEFAULT_GOAL := all

DOCKER_CMD := docker run -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$(DISPLAY) -h $(HOSTNAME) --rm -it --workdir /workspaces/gamequeer -v .:/workspaces/gamequeer --user $(CURRENT_UID):$(CURRENT_GID) $(project_name)-builder:latest

builder-build: builder.Dockerfile requirements.txt gq-game-language/install-langium-deps.sh 
	docker build -f builder.Dockerfile -t $(project_name)-builder:latest .
	@touch $@

builder-rebuild:
	docker build --no-cache -f builder.Dockerfile -t $(project_name)-builder:latest .
	@touch builder-build

builder-run:
	$(DOCKER_CMD) /bin/bash

### Build targets in subdirectories

gamequeer/build/gamequeer: builder-build
	$(DOCKER_CMD) /bin/bash -c "cd gamequeer && cmake -B build && cmake --build build"

# TODO: version number should be a variable
gqc/dist/gqc-0.0.1.tar.gz gqc/dist/gqc-0.0.1-py3-none-any.whl: builder-build
	$(DOCKER_CMD) /bin/bash -c "cd gqc && python -m build"

# TODO: version number should be a variable
# TODO: We should really be packaging this into the container
gq-game-language/gq-game-language-0.0.1.vsix: builder-build
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
