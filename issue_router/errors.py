"""Shared error type; kept separate so core.py and evaluators.py can both import it without a cycle."""


class RouterError(Exception):
    pass
