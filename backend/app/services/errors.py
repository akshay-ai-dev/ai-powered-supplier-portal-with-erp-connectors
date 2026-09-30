class DomainError(Exception):
    """Business-rule failure; routers map it to an HTTP status, MCP tools to a tool error."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFound(DomainError):
    def __init__(self, message: str = "Not found"):
        super().__init__(message, 404)


class Forbidden(DomainError):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, 403)
