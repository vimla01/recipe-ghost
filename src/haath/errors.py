"""Errors that always carry the exact fix, so nobody is left guessing."""


class HaathError(Exception):
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message = message
        self.fix = fix

    def __str__(self) -> str:
        return f"{self.message}\n  → fix: {self.fix}" if self.fix else self.message
