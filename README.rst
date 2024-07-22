=========================
GameQueer Fantasy Console
=========================
.. image:: https://img.shields.io/badge/license-MIT-blue.svg
   :target: https://opensource.org/licenses/MIT
   :alt: License: MIT
   
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
