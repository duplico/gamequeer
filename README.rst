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
the other Python dependencies. To install gqc to your system, run ``pip install`` on the
wheel file that was built in the previous step. Use of a virtual environment, pyenv, or
similar is recommended.

I use a pyenv environment initialized with ``pyenv virtualenv 3.10.0 gamequeer``.

To install the gqc module, run:

.. code-block:: bash

    pip install build/gqc-0.1.0-py3-none-any.whl

Note that depending on your distribution, ``pip`` may be need to be invoked using ``pip3``, 
``python3 -m pip``, or something else.

Building the GameQueer Emulator
-------------------------------

To build the gamequeer emulator (a binary called ``gamequeer``), make the following target:

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
cartridge. To run a game image, use the ``gamequeer`` command, passing the path to the game image
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

Simply put, a GameQueer game is made up of a ``.gq`` file, and a set of assets. The assets include
animations to be displayed on the OLED (which may be in any format that ffmpeg can read), and
LED lighting cues, which are simple text files that describe the colors and patterns of the LEDs.

Setting up your GameQueer workspace
-----------------------------------

Prerequisite: You must have the ``gqc`` module installed in your Python environment. It must be
invokable with the ``python -m gqc`` command. If a different command is required to invoke gqc,
you must set the ``GQC_CMD`` environment variable to that command.

A GameQueer workspace is a directory that contains all the assets and game source code required
to build one or more GameQueer games. If your goal is to build multiple completely standalone
games, you may want to set up multiple workspaces. However, the advantage of a single workspace
is that you can share assets between games.

To set up a new GameQueer game project, run the following command:

.. code-block:: bash

    python -m gqc init-dir /path/to/your/workspace

This will create a new directory at ``/path/to/your/workspace`` with the following structure:

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

The ``assets`` directory is where you'll put all your game assets. The ``assets/animations`` 
directory is where you'll put all your animation files, which can be in any format that 
ffmpeg can read. The ``assets/lightcues`` directory is where you'll put all your LED lighting 
cue files. The ``games`` directory is where you'll put all your game source code. The ``build/``
directory is used for build artifacts, including both intermediary files and the final game
image. It's set to be ignored by the .gitignore file, and it can be cleaned up at any time
to remove the build artifacts.

The workspace directory is intended to be a git repository (or a subdirectory of one), so a
``.gitignore`` file is provided to ignore the ``build`` directory and other generated files.

The Makefile provided can be used to build your games. It shouldn't need to change regularly,
even when you add new games to the workspace. The ``Makefile.local`` file is a generated file
that contains the paths to the assets and games directories, and should not be edited by hand.
Whenever you add a new game source file in the ``games`` directory, you should update the
``Makefile.local`` file by running the following command:

.. code-block:: bash

    make Makefile.local

This will update the ``Makefile.local`` file with paths to your game source files, and is
equivalent to running the command ``python -m gqc update-makefile-local .`` from the workspace
directory. This will generate new make targets for all your games, and also update the
``build`` directory structure based on the layout of your ``games`` and ``assets`` directories.

After you have run ``make Makefile.local``, you can build your game using ``make``. For example,
if your game source file is ``games/test.gq``, you can build it with the following command:

.. code-block:: bash

    make build/test.gqgame

This will build the game and place the resulting game image in the ``build`` directory.

Alternatively, you can build all the games in the workspace with the following command:

.. code-block:: bash

    make all

Creating assets
---------------

In GameQueer, assets refer to two different types of visual components that are used in games:
animations and light cues. Animations are visual sequences that are displayed on the OLED
display of the badge, and light cues are sequences of colors and patterns that are displayed
on the LEDs on either side of the display.

Animations are created as video files that can be read by ffmpeg. The GameQueer compiler
will automatically convert these video files into a format that can be displayed on the badge.

Light cues are created as text files that describe the colors and patterns of the LEDs. The
GameQueer compiler will read these text files and convert them into a format that can be
displayed on the badge.

Animations
^^^^^^^^^^

Any path specification that can be processed by ffmpeg may be used as the source for an
animation. Extensive testing has only been done with .mp4 files, but other formats should
work as well. The GameQueer compiler will automatically convert the video file into a format
that can be displayed on the badge.

Place the source video file in the ``assets/animations`` directory of your workspace. Games
will reference animations by their filename, relative to that directory. For example, if
you create ``assets/animations/test.mp4``, you can import it in a game source file as
``test.mp4``. If you create ``assets/animations/subdir/test.mp4``, you can import it as
``subdir/test.mp4``. Multiple games (and, in fact, multiple animations within a single game)
can reference the same animation file.

Light cues
^^^^^^^^^^

Light cues refer to the animations of the LEDs on either side of the OLED display. The display
has five vertically-oriented RGB LEDs on either side, shining generally outwards. The LEDs on
each side are electrically paired; for example, whatever is displayed on the top LED on one side
is also displayed on the top LED on the other side.

Light cue files use the ``.gqcue`` extension and are placed in the ``assets/lighting`` directory of
your workspace. The file hierarchy works the same as for animations: if a game refers to
``foo.gqcue``, it will look for that file at ``assets/lighting/foo.gqcue``.

Lighting cue files have two sections: the color definition section, and the frame definition
section. The color definition section is optional, and allows you to define custom colors by
hex code and assign them a name. The frame definition section is required, and describes the
frame by frame changes to the LEDs.

We'll start by describing the frame definition section, and then follow up with a description
of the color definition section. Often, you won't need a color definition section at all.
A frame definition section is just a sequence of frame definitions. There's no symbol needed
to enclose or delimit the frame definitions; they're just listed one after the other.

Here's an example of a frame definition:

.. code-block:: text

    frame {
        duration = 100;
        transition := "smooth";
        colors {
            red,
            orange,
            yellow,
            green,
            blue
        }
    }

The ``duration`` field is required. It specifies the duration of the frame in system ticks,
which are 10ms each. So a duration of 100 is 1 second. The ``transition`` field is optional,
and specifies how this frame transitions to the next. Valid values are either ``"smooth"``
or ``"none"``, which is also the default if no transition type is specified. A smooth
transition gradually fades from this frame to the next over its entire duration. 
Specifying ``"none"`` means this frame will hold steady for its duration, then abruptly change
to the next frame once it's complete.

The ``colors`` field is required, and specifies the colors of the LEDs for this frame. There
must be exactly 5 comma-separated colors, enclosed in curly braces. All named colors
included in the Python ``webcolors`` package are supported here, but we recommend that
you stick with CSS color names.

The color definition section allows you to define new colors by name, or overwrite the
built-in colors. Here's an example of a color definition section:

.. code-block:: text

    colors {
        my_red := "red";
        orange := "#ff2010";
    }

Color definitions support both overwriting the built-in colors and defining new colors.
You may use CSS color names to define your custom colors, but this isn't generally very
useful because you can also use the CSS color names directly in your frame definitions.
Most of the power of this feature comes from defining custom colors by hex code, which
are double-quoted strings that start with a hash mark, much like web hex colors.

Creating games
--------------

GameQueer games are written in a specialized language designed to lend itself well to
modestly interactive games with a focus on visual and lighting effects. The language
uses some C-like syntax, but is much simpler. Every game is a single file with a ``.gq``
extension, and is placed in the ``games`` directory of your workspace.

A GameQueer game has several global definition sections, which are used to define
global variables, animations, light cues, and menus. The game is then divided into
stages, which themselves are comprised of some basic configuration plus sets of
event handlers. The event handlers are where the game logic is implemented, and they 
are called in response to various events that occur during the game: for example, 
button presses, animations being completed, or timers. Each game begins with its 
"starting stage."

We'll go into the details of the syntax and general mechanics of the gq language
a little later, but for now, let's walk through a simple example game:

.. code-block:: text

    game {
        id = 0;
        title := "Tutorial 1";
        author := "duplico";
        starting_stage = start;
    }

    persistent {
        int high_score = 0;
        str high_score_name := "ME";
    }

    volatile {
        int score = 0;
    }

    animations {
        hearts <- "heart_anim.gif";
        pop <- "bwcircles.gif" {
            frame_rate = 10;
            dithering := "sierra2_4a";
        }
    }

    lightcues {
        flash <- "flash.gqcue";
    }
    menus {
        restart {
            1: "Yes";
            0: "No";
        }
    }

    stage start {
        event enter {
            timer 1000;
        }

        event timer {
            gostage end;
        }

        event input(A) {
            score = score + 1;
            play bganim pop;
            cue flash;
        }
    }

    stage end {
        menu restart prompt "Play again?";
        bganim hearts;

        event enter {
            if (score > high_score) {
                high_score = score;
                high_score_name := GQS_PLAYER_HANDLE;
            }
        }

        event bgdone {
            play bganim hearts;
        }

        event menu {
            if (GQI_MENU_VALUE == 0) {
                score = 0;
                gostage start;
            }
        }
    }

Let's break it down into its parts.

Game definition
^^^^^^^^^^^^^^^

Every game must start with a ``game`` block, which contains basic information about the game.
That information can be listed in any order, but it must include a numeric ``id``, a string
``title``, a string ``author``, and the name of the starting stage. This section must be
the first thing in the game file.

The ID is a unique identifier for the game, and is used to distinguish it from other games.
Its definition here shows an example of *numeric assignment* in gq, using the ``=`` operator.
The only numeric type in gq is ``int``, and it's a 32-bit signed integer.

The title is simply a display name for the game. Its assignment demonstrates *string
assignment*, using the ``:=`` operator. Strings may be up to 22 characters long. The author
field is also a display name, stored in a string, intended to record the author of the
game.

Finally, the ``starting_stage`` field is the name of the stage that the game should start in.
This field uses the ``=`` operator, but is a special case. It's a *stage reference*, which
probably shouldn't use the ``=`` operator, but it does. So sue me.

Variable definitions
^^^^^^^^^^^^^^^^^^^^

All variables in gq have global scope. There are two types: ``str`` and ``int``. As described
above, ``str`` is the string type, which is an up-to 22 character string, and ``int`` is a
signed 32-bit integer. The variables are defined in sections that specify their storage
class: ``persistent``, which is stored on the game cartridge and persists between plays, and
``volatile``, which is stored in RAM and is reset between plays.

All variables require an initial value, which is set with the ``=`` operator for ``int`` and
the ``:=`` operator for ``str``.

The variable sections are optional. If you don't need any variables of a particular
storage class, you may omit the section.

Menu definitions
^^^^^^^^^^^^^^^^

GameQueer has a concept of modal menus, which may be called from any stage. Menus map
an integer ``value`` to a string ``label``. The ``value`` is returned to the game in an
event when the menu selection is made. The ``label`` is what's displayed on the screen
for the user to select. The values do not need to be contiguous, and they also do not
need to be unique. I don't know why you would have non-unique labels in a menu, but
technically that's also allowed.

This section defines two callable menus, ``YesNo`` and ``OkCancel``. The ``YesNo`` menu has
two options, with values 1 and 0, and the `Ok`Cancel` menu also has two options, with
values 25 and -5. The values may be any supported ``int``, and the labels may be any
supported ``str``.

Animation definitions
^^^^^^^^^^^^^^^^^^^^^

Animations are defined in the ``animations`` section. This section introduces a new
operator, the ``<-`` or file load operator. In the animation section, the left-hand
side of the file load operator specifies the name of an animation, and the right-hand
side specifies the path to the animation file, plus an optional configuration block.

The configuration block is optional, and currently only allows the ``dithering`` and
``frame_rate`` fields. The ``dithering`` field specifies the dithering algorithm to use
when converting the video to the badge's display format. The ``frame_rate`` field
specifies the frame rate of the video, in frames per second. Note that frames are
displayed in a 100 Hz loop, so the frame rate will be rounded to something that
evenly divides 100. The compiler will emit a warning if the frame rate rounded.
The default frame rate is 25 fps.

Light cue definitions
^^^^^^^^^^^^^^^^^^^^^

Light cues are defined in the ``lightcues`` section. The syntax is the same as for
animations, with the left-hand side of the file load operator specifying the name
of the light cue, and the right-hand side specifying the path to the light cue file.
There are no configuration options for light cues.

Stage definitions
^^^^^^^^^^^^^^^^^

Stages are the main building blocks of a GameQueer game. Each game must have at least
one stage, and the game starts in the stage specified in the ``starting_stage`` field of
the game definition. Each stage is defined in a ``stage`` block.

Each stage has some optional configuration declarations. A ``bganim`` declaration specifies
the background animation to display on the OLED. A ``bgcue`` declaration specifies the
looping background lighting cue to display on the LEDs. And, the ``menu`` declaration
specifies the menu to display when the stage is entered. The menu will be displayed on top
of the OLED animations.

Aside from the configuration declarations, stages are comprised of event handlers. The
event handlers are called in response to various events that occur during the game. The
``enter`` event is called when the stage is entered. The ``input`` event is called when a
button is pressed. The ``timer`` event is called when a timer expires. The ``bgdone`` event
is called when the background animation has completed. The ``menu`` event is called when
a menu selection is made.

Event commands
^^^^^^^^^^^^^^

The event handlers are where the game logic is implemented. They are comprised of a series
of commands that are executed in sequence.

The following event types are allowed:

``enter``
    Called when the stage is entered

``input(A)``
    Called when button A is pressed

``input(B)``
    Called when button B is pressed

``input(<-)``
    Called when the D-Dial is rotated left

``input(->)``
    Called when the D-Dial is rotated right

``input(-)``
    Called when the D-Dial is clicked

``timer``
    Called when a timer expires

``bgdone``
    Called when the background animation has completed

``menu``
    Called when a menu selection is made

Inside an event, the following commands are available:

``cue``
    Play a lighting cue by name; for example, ``cue flash``

``play bganim``
    Play a new background animation by name; for exmaple, ``play bganim pop``

``gostage``
    Go to a different stage; for example, ``gostage end``

``timer``
    Set a one-shot timer by a numeric expression. The interval is measured in
    system ticks, which are 10ms each. For example, ``timer 1000`` sets a timer for 10 seconds.

The following operators are available:

Unary operators (one operand, right-associative):

``-``
    Unary negation. The right hand side is negated. The value of the expression is the
    negation of the right hand side.

``!``
    Logical NOT. The right hand side is negated. The value of the expression is 1 if the
    right hand side is equal to 0, and 0 otherwise.

Binary operators (two operands):

``=``
    Numeric assignment. The integer variable on the left hand side is assigned the value
    of the expression on the right hand side.

``:=``
    String assignment. The string variable on the left hand side is assigned the value
    of the expression on the right hand side.

``+``
    Numeric addition. The left and right hand sides are added together.

``-``
    Numeric subtraction. The right hand side is subtracted from the left hand side.

``*``
    Numeric multiplication. The left and right hand sides are multiplied together.

``/``
    Numeric division. The left hand side is divided by the right hand side.

``%``
    Numeric modulo. The left hand side is divided by the right hand side, and the
    expression takes the value of the remainder.

``==``
    Numeric equality. The left and right hand sides are compared for equality. The value
    of the expression is 1 if they are equal, and 0 if they are not.

``!=``
    Numeric inequality. The left and right hand sides are compared for inequality. The
    value of the expression is 1 if they are not equal, and 0 if they are equal.

``>``, ``>=``, ``<``, and ``<=``
    Numeric comparison. The left and right hand sides are compared
    for greater than, greater than or equal, less than, and less than or equal, respectively.
    The value of the expression is 1 if the comparison is true, and 0 if it is false.

``&&``
    Logical AND. The left and right hand sides are compared for truth. The value of the
    expression is 1 if both sides are true, and 0 if either side is false. Does NOT support
    short-circuit evaluation.

``||``
    Logical OR. The left and right hand sides are compared for truth. The value of the
    expression is 1 if either side is true, and 0 if both sides are false. Does NOT support
    short-circuit evaluation.

The following control structures are available:

``if``
    The ``if`` statement allows you to conditionally execute a block of code. The gqc
    syntax for ``if`` statements is similar to C. The ``if`` statement must be followed by a
    condition in parentheses, followed by the code to be executed if the condition is true.
    The code block may be a single command, or a block of commands enclosed in curly braces.
    The ``if`` statement may be followed by an optional ``else`` statement, which is executed
    if the condition is false. If the ``else`` statement is included, it must be followed by a
    code block. It's permitted to use an ``else if`` structure.

``loop``
    The ``loop`` statement allows you to execute a block of code
    repeatedly. The loop statement must be followed by a command or a block of commands
    enclosed in curly braces, which will be executed repeatedly until a ``break`` statement.
    Note that there are no built-in conditionals for loops; you must implement it yourself
    with ``if`` statements.

``break``
    Exit the innermost loop.

``continue``
    Skip the rest of the current iteration of the innermost loop.
