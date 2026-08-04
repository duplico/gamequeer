"""Comment- and layout-preserving concrete syntax tree (CST) for `.gq`
source files.

Step 1 of the formatter/linter foundation (gamequeer#424, DEF CON sprint
epic gamequeer#419). This module is **additive**: `grammar.build_game_parser()`
/ `parser.parse()` (the compile path) are untouched, and nothing here is on
that path. `gqc fmt` (see `gqc.py`) is the only current consumer.

Why a separate parser instead of reusing `grammar.py`
-------------------------------------------------------
`grammar.py`'s pyparsing grammar is built for *compilation*: its parse
actions have real side effects (populating `Game.game`, `Cohort.cohort_table`,
`Variable`/`Stage`/`Event` registries, folding constant expressions, ...),
and it discards comments outright via `.ignore(pp.cppStyleComment)` since
compilation never needs them. Layering a lossless, comment-preserving mode
on top of that grammar would mean either running it with all those side
effects live (wrong for a tool like `fmt` that must work on
work-in-progress, possibly-invalid source) or forking every parse action in
it (a maintenance burden that would fight the "additive, reviewable
increment" scope of this step). So this is a second, independent, much
simpler parser purpose-built for losslessness.

What kind of CST this is (and isn't) -- the documented gap
------------------------------------------------------------
This is a **generic token/trivia tree, structured by bracket nesting**
(`{ }` and `( )`), not a fully-typed tree with one node kind per grammar
production (`game_definition_section`, `stage_definition_section`, ...).
It doesn't know that `stage foo { ... }` is a stage, or that `x = 1 + 2;`
is an assignment -- it just knows there's a run of tokens, then a
brace-delimited `Group`, in document order, with every byte of the
original file accounted for as either a `Token` or `Trivia`.

That's a deliberate scope cut for this step, not an oversight: a
per-production CST would mean re-deriving (and keeping in lockstep with)
every one of `grammar.py`'s ~30 rules, which is exactly the kind of
big-bang rewrite the issue asks this step to avoid. The generic tree above
is already sufficient to prove losslessness (this module's actual job) and
to drive brace-depth-based reindentation later. A later step that wants
per-construct semantic node types (e.g. for lint rules like "unused
variable" or "duplicate stage name") can layer that on top of this tree --
or cross-reference it against `datamodel.py`'s already-typed objects, which
carry their own `instring`/`loc` back to the same source positions this
module uses -- without needing to touch this file's tokenizer.

Trivia attachment and the string-escaping simplification are two smaller
documented gaps; see `Trivia`/`_tokenize` below.
"""

from dataclasses import dataclass, field
from typing import Union

import pyparsing as pp

from . import GqcParseError

# Punctuation/operator lexemes recognized by grammar.py, sorted longest-first
# so the tokenizer's maximal-munch scan tries e.g. ":=" before "=" and "<<"
# before "<". "{"/"}"/"("/")" are included here too (they're ordinary Tokens
# like any other punctuation -- bracket *nesting* is a second pass over the
# resulting token stream, see `_group`).
_PUNCTUATION = sorted(
    [
        ":=", "<-", "..", "->", "<=", ">=", "==", "!=", "&&", "||", "<<", ">>",
        "{", "}", "(", ")", ";", ",", ":", ".", "=",
        "+", "-", "*", "/", "%", "!", "~", "&", "|", "^", "<", ">",
    ],
    key=len,
    reverse=True,
)

_OPEN_TO_CLOSE = {"{": "}", "(": ")"}
_CLOSE_TO_OPEN = {v: k for k, v in _OPEN_TO_CLOSE.items()}

_WORD_START = pp.alphas + "_"
_WORD_BODY = pp.alphanums + "_"


@dataclass
class Trivia:
    """A run of whitespace, or a single comment, between two tokens.

    `kind` is one of "whitespace" | "line_comment" | "block_comment".
    `text` is the exact source text (for a comment, including its own
    delimiters: "//...", "/*...*/")."""

    kind: str
    text: str
    start: int
    end: int


@dataclass
class Token:
    """A single lexeme: an identifier/keyword, an integer literal, a
    quoted string literal, or one piece of punctuation/an operator (see
    `_PUNCTUATION`). `kind` is one of "word" | "number" | "string" | "punct".

    `leading_trivia` is every `Trivia` run since the previous token (or
    since the start of the file, for the very first token) -- this is a
    leading-only attachment convention (there's no separate "trailing
    trivia" on a token; what would be "trailing" for token N is leading
    for token N+1, or the file's own `trailing_trivia` if N is the last
    token). That's enough to reconstruct the source exactly (see
    `to_source`) and to tell, e.g., a same-line trailing comment from a
    comment on its own line (by checking for a newline in the trivia text
    before it) -- which is what a formatter needs to decide where to put a
    comment back, without needing a second, redundant trailing-trivia
    slot."""

    kind: str
    text: str
    start: int
    end: int
    leading_trivia: list = field(default_factory=list)


@dataclass
class Group:
    """A bracket-delimited region: `{ ... }` or `( ... )`. `open`/`close`
    are the delimiter `Token`s themselves (so their `leading_trivia`,
    e.g. a comment right after `{`, is preserved); `children` is the
    (`Token` | `Group`) sequence strictly between them, in document
    order."""

    open: Token
    close: Token
    children: list


@dataclass
class CstFile:
    """The whole-file root. `children` is the top-level (`Token` | `Group`)
    sequence; `trailing_trivia` is whatever whitespace/comments follow the
    very last token (there's no token to attach it to as leading trivia)."""

    source: str
    children: list
    trailing_trivia: list = field(default_factory=list)


Node = Union[Token, Group, CstFile]


def pos_to_linecol(source: str, pos: int) -> tuple:
    """1-based (line, column) for a character offset into `source`, using
    the same convention (and the same pyparsing helpers) as
    `GqcParseError`/the rest of gqc's diagnostics."""
    return pp.lineno(pos, source), pp.col(pos, source)


def _tokenize(source: str):
    """Scan `source` into a flat list of `Token`s (each carrying its own
    `leading_trivia`) plus whatever trivia trails the last token. Consumes
    every character of `source` as either trivia or token text -- that
    completeness is what makes `to_source(parse_cst(source)) == source`
    hold by construction, rather than needing to be checked separately.

    Raises `GqcParseError` on an unterminated string/block comment or an
    unrecognized character, both located via the same `(instring, loc)`
    convention the rest of gqc's parse errors use.
    """
    n = len(source)
    i = 0
    tokens = []
    pending_trivia = []

    def add_trivia(kind, start, end):
        pending_trivia.append(Trivia(kind, source[start:end], start, end))

    while i < n:
        c = source[i]

        # Whitespace
        if c in " \t\r\n\f\v":
            start = i
            while i < n and source[i] in " \t\r\n\f\v":
                i += 1
            add_trivia("whitespace", start, i)
            continue

        # Line comment
        if source.startswith("//", i):
            start = i
            i += 2
            while i < n and source[i] not in "\r\n":
                i += 1
            add_trivia("line_comment", start, i)
            continue

        # Block comment
        if source.startswith("/*", i):
            start = i
            end = source.find("*/", i + 2)
            if end == -1:
                raise GqcParseError("Unterminated block comment", source, start)
            i = end + 2
            add_trivia("block_comment", start, i)
            continue

        # String literal. grammar.py has two subtly different quoted-string
        # rules (a plain `pp.QuotedString('"')` with no escape handling at
        # all for game/menu/stage strings, vs. `escChar='\\'` for
        # animation/lightcue file paths) -- this generic tokenizer can't
        # tell which grammar context it's in (that's the whole point of
        # being generic), so it documents-and-picks one lexing rule for
        # both: `\"` never terminates the string, and `\\` is a literal
        # escaped backslash. That's a strict superset of the no-escape
        # rule for any string that doesn't itself contain a backslash
        # (true of every string in every committed example game as of this
        # writing), so it's a safe, deliberate simplification rather than
        # a silent behavior difference -- see the module docstring's
        # "documented gap" section.
        if c == '"':
            start = i
            i += 1
            while i < n and source[i] != '"':
                if source[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            if i >= n:
                raise GqcParseError("Unterminated string literal", source, start)
            i += 1  # closing quote
            tokens.append(Token("string", source[start:i], start, i, pending_trivia))
            pending_trivia = []
            continue

        # Word: identifier/keyword
        if c in _WORD_START:
            start = i
            i += 1
            while i < n and source[i] in _WORD_BODY:
                i += 1
            tokens.append(Token("word", source[start:i], start, i, pending_trivia))
            pending_trivia = []
            continue

        # Number: a bare run of digits. Unlike grammar.py's `integer` rule,
        # a leading "-" is always its own separate "punct" token here (see
        # `_PUNCTUATION`) rather than sometimes being fused into the
        # number -- grammar.py only fuses it because it has to decide
        # there and then between a negative literal and a unary-minus
        # operator, a semantic distinction this tokenizer never needs to
        # make: either split reconstructs the same source text via
        # `to_source`.
        if c.isdigit():
            start = i
            i += 1
            while i < n and source[i].isdigit():
                i += 1
            tokens.append(Token("number", source[start:i], start, i, pending_trivia))
            pending_trivia = []
            continue

        # Punctuation/operators, longest-match-first.
        matched = None
        for punct in _PUNCTUATION:
            if source.startswith(punct, i):
                matched = punct
                break
        if matched is not None:
            start = i
            i += len(matched)
            tokens.append(Token("punct", matched, start, i, pending_trivia))
            pending_trivia = []
            continue

        raise GqcParseError(f"Unrecognized character {c!r}", source, i)

    return tokens, pending_trivia


def _group(tokens, source):
    """Second pass: nest a flat `Token` stream into `Group`s by matching
    `{}`/`()`. Raises `GqcParseError` (located against `source`, same
    convention as the rest of gqc's diagnostics) on a mismatched or
    unterminated bracket."""
    root = []
    # Stack of (open_token, expected_close, children_being_built).
    stack = []

    for tok in tokens:
        if tok.kind == "punct" and tok.text in _OPEN_TO_CLOSE:
            stack.append((tok, _OPEN_TO_CLOSE[tok.text], []))
            continue
        if tok.kind == "punct" and tok.text in _CLOSE_TO_OPEN:
            if not stack:
                raise GqcParseError(
                    f"Unexpected closing {tok.text!r} with no matching opener",
                    source,
                    tok.start,
                )
            open_tok, expected_close, children = stack.pop()
            if tok.text != expected_close:
                raise GqcParseError(
                    f"Mismatched bracket: {open_tok.text!r} opened at "
                    f"offset {open_tok.start} closed with {tok.text!r}",
                    source,
                    tok.start,
                )
            group = Group(open=open_tok, close=tok, children=children)
            (stack[-1][2] if stack else root).append(group)
            continue
        (stack[-1][2] if stack else root).append(tok)

    if stack:
        open_tok, _, _ = stack[-1]
        raise GqcParseError(
            f"Unterminated {open_tok.text!r} opened at offset {open_tok.start}",
            source,
            open_tok.start,
        )

    return root


def parse_cst(source: str) -> CstFile:
    """Parse `source` (a `.gq` file's full text) into a lossless CST. See
    the module docstring for what "lossless" and "CST" mean here."""
    tokens, trailing_trivia = _tokenize(source)
    children = _group(tokens, source)
    return CstFile(source=source, children=children, trailing_trivia=trailing_trivia)


def _write_trivia(out: list, trivia_list):
    for t in trivia_list:
        out.append(t.text)


def to_source(node: Node) -> str:
    """Reconstruct the exact source text a CST node was parsed from, by
    concatenating leading trivia and token text in document order.
    `to_source(parse_cst(text)) == text` for any `text` that tokenizes
    cleanly -- this is the round-trip guarantee the CST exists to provide,
    and it's what `gqc fmt` step 1 (see `gqc.py`) uses to prove the CST is
    lossless before any real formatting logic is layered on top of it."""
    out = []
    _write(node, out)
    return "".join(out)


def _write(node: Node, out: list) -> None:
    if isinstance(node, Token):
        _write_trivia(out, node.leading_trivia)
        out.append(node.text)
    elif isinstance(node, Group):
        _write(node.open, out)
        for child in node.children:
            _write(child, out)
        _write(node.close, out)
    elif isinstance(node, CstFile):
        for child in node.children:
            _write(child, out)
        _write_trivia(out, node.trailing_trivia)
    else:
        raise TypeError(f"Not a CST node: {node!r}")


def render(tree: CstFile) -> str:
    """`gqc fmt`'s entry point for turning a parsed CST back into source
    text. Step 1 (gamequeer#424) deliberately performs no reformatting --
    `render` is exactly `to_source`, i.e. an identity transform -- so that
    landing the CST and proving it lossless is its own reviewable
    increment, separate from any actual pretty-printing/reindentation
    policy (explicitly deferred to a follow-on step by the issue). Once
    that policy exists, it replaces this function's body; nothing about
    the CST shape above needs to change for it to do so."""
    return to_source(tree)


def iter_tokens(node: Node):
    """Depth-first iterator over every `Token` in `node` (a `CstFile`,
    `Group`, or `Token`), in document order. Convenience for tests and for
    any future pass that wants a flat view of the token stream (e.g. a
    linter walking for a specific keyword)."""
    if isinstance(node, Token):
        yield node
    elif isinstance(node, Group):
        yield node.open
        for child in node.children:
            yield from iter_tokens(child)
        yield node.close
    elif isinstance(node, CstFile):
        for child in node.children:
            yield from iter_tokens(child)
    else:
        raise TypeError(f"Not a CST node: {node!r}")


def iter_comments(node: Node):
    """Depth-first iterator over every comment `Trivia` (kind
    "line_comment" or "block_comment") attached anywhere in `node`, in
    document order. Convenience for tests/tools asserting comments
    survived a round-trip without needing to walk trivia manually."""
    if isinstance(node, CstFile):
        for child in node.children:
            yield from iter_comments(child)
        for t in node.trailing_trivia:
            if t.kind != "whitespace":
                yield t
    elif isinstance(node, Group):
        yield from iter_comments(node.open)
        for child in node.children:
            yield from iter_comments(child)
        yield from iter_comments(node.close)
    elif isinstance(node, Token):
        for t in node.leading_trivia:
            if t.kind != "whitespace":
                yield t
    else:
        raise TypeError(f"Not a CST node: {node!r}")
