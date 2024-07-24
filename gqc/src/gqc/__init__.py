__version__ = '0.1.0'

class GqcParseError(Exception):
    def __init__(self, message, s, loc):
        message = f"Error at line {pp.lineno(loc, s)}, column {pp.col(loc, s)}: {message}"
        super().__init__(message)
