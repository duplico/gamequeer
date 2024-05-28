# Makefile for GQC

GQC_CMD := "python -m gqc"

BASE_DIR:=$(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))
GAMES := $(shell find $(BASE_DIR)/games -name "*.gq" -print)

.PHONY: clean

Makefile.local: $(GAMES)
	$(GQC_CMD) update-makefile-local

include Makefile.proj

clean:
	rm -rf build/* Makefile_proj

