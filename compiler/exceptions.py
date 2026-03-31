"""
4ML Compiler Exceptions

Custom exception classes for the 4ML compiler to replace magic number-based
throw_error/throw_warning functions.
"""

import sys

# Terminal colors (copied from compiler.py/utils.py for standalone use)
class _bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class CompilerError(Exception):
    """Base exception for compiler errors"""
    pass


class FileError(CompilerError):
    """File not found"""
    pass


class LimitError(CompilerError):
    """Too many channels, patterns, or loop closes"""
    pass


class SyntaxError(CompilerError):
    """Unclosed loop or other syntax error"""
    pass


class CompilerValueError(CompilerError):
    """Invalid value - missing, out of range, or bad duration"""
    pass


class CompilerWarning(Exception):
    """Base warning - doesn't cause exit"""
    pass


# Helper function to print error and exit
def handle_error(error: CompilerError) -> None:
    """Print error message and exit"""
    print(f"{_bcolors.FAIL}ERROR: {_bcolors.ENDC}", end='', file=sys.stderr)
    print(str(error), file=sys.stderr)
    sys.exit(1)


# Helper function to print warning
def handle_warning(warning: CompilerWarning) -> None:
    """Print warning message"""
    print(f"{_bcolors.WARNING}WARNING: {_bcolors.ENDC}", end='', file=sys.stderr)
    print(str(warning), file=sys.stderr)
