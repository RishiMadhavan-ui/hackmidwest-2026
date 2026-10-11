"""Errors safe to return without credentials, SQL or client payloads."""


class AuthorityError(Exception):
  def __init__(self, status: int, detail: str):
    self.status = status
    self.detail = detail
    super().__init__(detail)


class DatabaseUnavailable(Exception):
  pass
