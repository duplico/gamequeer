makefile_skel = """\
# Makefile for GQC

GQC_CMD := "GQCCMD"

BASE_DIR:=$(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))
GAMES := $(shell find $(BASE_DIR)/games -name "*.gq" -print)

.PHONY: clean

Makefile.local: $(GAMES)
\t$(GQC_CMD) update-makefile-local

include Makefile.proj

clean:
\trm -rf build/* Makefile_proj

"""

