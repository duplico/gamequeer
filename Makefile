project_name=gamequeer
BASE_DIR:=$(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))
IMAGES:=$(shell docker images $(project_name)-builder -a -q)

.PHONY: clean all builder-run gqc gamequeer gq-game-language
.DEFAULT_GOAL := all

builder-build: builder.Dockerfile
	docker build -f builder.Dockerfile -t $(project_name)-builder:latest .
	@touch $@

builder-run:
	docker run \
		--rm \
		-it \
		--workdir /builder/mnt \
		-v .:/builder/mnt \
		$(project_name)-builder:latest \
		/bin/bash

### Build targets in subdirectories

gamequeer/build/gamequeer: builder-build
	docker run \
		--rm \
		-it \
		--workdir /builder/mnt \
		-v .:/builder/mnt \
		$(project_name)-builder:latest \
		/bin/bash -c "cd gamequeer && cmake -B build && cmake --build build"

# TODO: version number should be a variable
gqc/dist/gqc-0.0.1.tar.gz gqc/dist/gqc-0.0.1-py3-none-any.whl: builder-build
	docker run \
		--rm \
		-it \
		--workdir /builder/mnt \
		-v .:/builder/mnt \
		$(project_name)-builder:latest \
		/bin/bash -c "cd gqc && python -m build"

# TODO: version number should be a variable
# TODO: We should really be packaging this into the container
gq-game-language/gq-game-language-0.0.1.vsix: builder-build
	docker run \
		--rm \
		-it \
		--workdir /builder/mnt \
		-v .:/builder/mnt \
		$(project_name)-builder:latest \
		/bin/bash -c "cd gq-game-language && vsce package --allow-missing-repository"

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

clean:
ifeq ($(IMAGES),)
	@echo "No images to remove"
else
	docker rmi $(IMAGES)
endif
	rm -f build/*
	rm -f builder-build
	rm -f gamequeer/build/gamequeer
	rm -f gqc/dist/gqc-0.0.1.tar.gz
	rm -f gqc/dist/gqc-0.0.1-py3-none-any.whl
	rm -f gq-game-language/gq-game-language-0.0.1.vsix

