=========================
GameQueer Fantasy Console
=========================

Introduction
============

This repository contains the development toolchain for the GameQueer fantasy game console.

GameQueer is a sort of `Fantasy Console <https://en.wikipedia.org/wiki/Fantasy_video_game_console>`_, 
with a couple of twists. First, there is an actual console of sorts, in the form
of the 2024 Queercon badge---so in that sense, it's not entirely fantasy. Second, the "games"
aren't really meant to be full-fledged console games, but rather more like interactive art:
visual animations, LED lighting cues, with a focus on enabling a collaborative social
experience among badgeholders.

The GameQueer console is comprised of a 128x128 pixel black and white OLED display, 5 linked 
pairs of vertically-oriented RGB LEDs on either side of the display, two buttons, and a D-pad
shaped rotary encoder called the "D-Dial" that can be both rotated and clicked, although 
clicking the dial is a system function not available to games. Games are written in a custom
language whose toolchain is provided in this repository.

Physical games are written to a game cartridge with 16 MB of NOR flash storage and an LED.
That 16 MB includes all animation artwork, LED lighting cues, game logic, and both persistent
and volatile variables, including their initialization tables.

Also included is an emulator for the GameQueer console, which can be used to test games on a
computer without needing to have a physical badge.

Building the toolchain
======================

The GameQueer toolchain is comprised of three main components: the compiler, the emulator, and
a VSCode extension for GameQueer code. The compiler is written largely in Python, and the 
emulator is written in C, sharing code with the badge firmware.

A Dockerfile is provided to build the entire toolchain. Once it's built, it can either be run
from inside the Docker container, or the built artifacts can be run from the host system.

The toolchain was developed on a combination of Ubuntu 20.04 in WSL2 on Windows 11 (AMD64), 
Debian Bookworm on a ChromeBook (ARM64), and Debian Bookworm in the included Docker container,
running on both platforms. It should run on most Linux systems, including in WSL2, and likely
on macOS as well. The compiler should run natively on Windows without WSL2, though that's not
well tested, but the emulator will not, as it specifically requires X11 to work.

In a fun twist, each of the subprojects has its own build system: Python setuptools for the
compiler, CMake for the emulator, and npm/Yeoman for the VSCode extension. I've provided a
Makefile in the root of the repository to build the Docker container and use it to invoke
all the subproject build systems, so you shouldn't need to interact with them directly.

Everything is designed to work with VSCode and, to a lesser extent, Theia.

TL;DR: Make everything and install it
-------------------------------------

Dependencies:

* Docker
* ffmpeg

.. code-block:: bash

    make all

    pip install build/gqc-0.1.0-py3-none-any.whl
    code --install-extension build/gq-game-language.vsix

There's no guarantee that the version of the gamequeer emulator built inside the 
container will work on your host system. If it doesn't, you need to build it natively on your
host. If it does, go ahead and install it:

.. code-block:: bash

    sudo cp build/gamequeer /usr/local/bin/

Building the Docker container
-----------------------------

The only real dependency for building the Docker container is Docker itself. I've tested this
on Linux and WSL2. It should be straightforward on macOS as well (including on ARM64 Macs), 
but I haven't tested it there. It will likely work on Windows without WSL2, but I haven't
tested that either.

To build the Docker container, run the following command from the root of the repository:

.. code-block:: bash

    make builder-build

If you want to log into the container and run interactively, you can do so with:

.. code-block:: bash

    make builder-run

If you're using VSCode, you can also use the Remote - Containers extension to open the repository
in a container. This is the recommended way to develop on the toolchain itself, but isn't
strictly necessary if your goal is just to build games.

Building gqc (GameQueer Compiler)
---------------------------------

The compiler is written in Python, and is built using setuptools. To build the compiler, run:

.. code-block:: bash

    make gqc

Installing gqc to your system
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The only real dependencies for gqc are Python 3.10 or later, pip, and ffmpeg. Pip will install
the other Python dependencies. To install gqc to your system, run `pip install` on the
wheel file that was built in the previous step. Use of a virtual environment, pyenv, or
similar is recommended.

I use a pyenv environment initialized with `pyenv virtualenv 3.10.0 gamequeer`.

To install the gqc module, run:

.. code-block:: bash

    pip install build/gqc-0.1.0-py3-none-any.whl

Note that depending on your distribution, `pip` may be need to be invoked using `pip3`, 
`python3 -m pip`, or something else.

Building the GameQueer Emulator
-------------------------------

To build the gamequeer emulator (a binary called `gamequeer`), make the following target:

.. code-block:: bash

    make gamequeer

If your host system is a glibc Linux distribution running the same version of glibc as the 
container, which is likely if you're running Ubuntu 20.04 or Debian Bookworm (or derivative),
you can install the emulator to your system as compiled by the container with a simple copy 
command:

.. code-block:: bash

    sudo cp build/gamequeer /usr/local/bin/

However, if you try to run the emulator and it crashes with an error that looks similar to
this:

.. code-block:: bash

    ./gamequeer: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.33' not found (required by ./gamequeer)

then you'll need to build the emulator directly on your host system, or run it from inside the container.

TODO: Docs for this case.

Building the VSCode Extension
-----------------------------

GameQueer has a simple VSCode extension providing syntax highlighting and very rudimentary
validation. To build the extension, run:

.. code-block:: bash

    make gq-game-language

To install it in vscode, run:

.. code-block:: bash

    code --install-extension build/gq-game-language.vsix

It should be possible to install and run it inside of Theia as well, but I haven't tested that yet.

Running a game image
====================

The GameQueer emulator can run a game image directly, without needing to flash it to a physical
cartridge. To run a game image, use the `gamequeer` command, passing the path to the game image
as an argument. For example:

.. code-block:: bash

    gamequeer games/test.gqgame

In the emulator, the 'A' and 'D' buttons are mapped to twisting the D-Dial one click to the left
or right, respectively. The 'K' and 'L' keys are mapped to the 'B' and 'C' buttons, respectively.
Pressing the spacebar is mapped to clicking the D-Dial, a system function.

Developing a game
=================

Introduction
------------

GameQueer games are written in a custom language designed around the constraints of the 2024
Queercon badge. It's a simple declarative language with a small number of imperative features,
designed around setting up transitions between animations and lighting cues based on events.

GameQueer games are written in a development environment with a specific directory structure,
which the gqc toolchain can set up and manage for you. This is how it knows where to find your
game code and assets, to produce the final game image that can be flashed to a cartridge or run
in the emulator.

Simply put, a GameQueer game is made up of a `.gq` file, and a set of assets. The assets include
animations to be displayed on the OLED (which may be in any format that ffmpeg can read), and
LED lighting cues, which are simple text files that describe the colors and patterns of the LEDs.

Setting up your GameQueer workspace
-----------------------------------

Prerequisite: You must have the `gqc` module installed in your Python environment. It must be
invokable with the `python -m gqc` command. If a different command is required to invoke gqc,
you must set the `GQC_CMD` environment variable to that command.

A GameQueer workspace is a directory that contains all the assets and game source code required
to build one or more GameQueer games. If your goal is to build multiple completely standalone
games, you may want to set up multiple workspaces. However, the advantage of a single workspace
is that you can share assets between games.

To set up a new GameQueer game project, run the following command:

.. code-block:: bash

    gqc init-dir /path/to/your/workspace

This will create a new directory at `/path/to/your/workspace` with the following structure:

.. code-block:: bash

    /path/to/your/workspace
    ├── assets/
    │   ├── animations
    │   └── lightcues
    ├── build/
    │   └── assets
    │       ├── animations
    │       └── lightcues
    ├── games/
    ├── .gitignore
    ├── Makefile
    └── Makefile.local

The `assets` directory is where you'll put all your game assets. The `assets/animations` 
directory is where you'll put all your animation files, which can be in any format that 
ffmpeg can read. The `assets/lightcues` directory is where you'll put all your LED lighting 
cue files. The `games` directory is where you'll put all your game source code. The `build/`
directory is used for build artifacts, including both intermediary files and the final game
image. It's set to be ignored by the .gitignore file, and it can be cleaned up at any time
to remove the build artifacts.

The workspace directory is intended to be a git repository (or a subdirectory of one), so a
`.gitignore` file is provided to ignore the `build` directory and other generated files.

The Makefile provided can be used to build your games. It shouldn't need to change regularly,
even when you add new games to the workspace. The `Makefile.local` file is a generated file
that contains the paths to the assets and games directories, and should not be edited by hand.
Whenever you add a new game source file in the `games`` directory, you should update the
`Makefile.local` file by running the following command:

.. code-block:: bash

    make Makefile.local

This will update the `Makefile.local` file with paths to your game source files, and is
equivalent to running the command `python -m gqc update-makefile-local .` from the workspace
directory. This will generate new make targets for all your games, and also update the
`build` directory structure based on the layout of your `games` and `assets` directories.

After you have run `make Makefile.local`, you can build your game using `make`. For example,
if your game source file is `games/test.gq`, you can build it with the following command:

.. code-block:: bash

    make build/test.gqgame

This will build the game and place the resulting game image in the `build` directory.

Alternatively, you can build all the games in the workspace with the following command:

.. code-block:: bash

    make all
