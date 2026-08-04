__version__ = '0.1.0'

import pyparsing as pp

class GqcParseError(Exception):
    def __init__(self, message, s, loc):
        message = f"Error at line {pp.lineno(loc, s)}, column {pp.col(loc, s)}: {message}"
        super().__init__(message)

class GqcAssetNotFoundError(ValueError):
    """An animation/lightcue asset was not found at its resolved path.
    On the compile path (anim.py/Animation.__init__) that path is always
    game-dir-relative (gamequeer#420); `gqc mkcue`'s standalone entry point
    (cues.make_cue) raises this too, for a user-supplied `src_path` that
    isn't necessarily game-dir-relative at all.

    Distinct from a plain ValueError so callers with game-name context
    (parser.py, which catches this to append a `gqc migrate` hint) can
    single it out without treating every other ValueError from asset
    processing (bad dithering option, malformed cue, ...) as a possible
    layout problem."""
