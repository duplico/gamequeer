makefile_skel = """\
# Makefile for GQC workspace
#  This file is generated by GQC and will be overwritten if you run `gqc init-dir --force`.
#  However, it's generally not needed to run that command. So, if you're careful to avoid that,
#  you're free to edit this file however you like.

ifndef GQC_CMD
# You'll want to alter this line if you need to invoke gqc with a different command:
GQC_CMD := GQCCMD
endif

BASE_DIR:=$(realpath $(shell dirname $(firstword $(MAKEFILE_LIST))))
GAMES := $(shell find $(BASE_DIR)/games -name "*.gq" -print)

.PHONY: clean

.DEFAULT_GOAL := Makefile.local

Makefile.local: $(GAMES)
\t$(GQC_CMD) update-makefile-local $(BASE_DIR)

-include Makefile.local

clean:
\t-rm -rf build/* Makefile.local

"""

