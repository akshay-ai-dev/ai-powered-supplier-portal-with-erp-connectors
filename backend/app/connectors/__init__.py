from ..config import settings
from .base import ERPConnector
from .infor import MockInforConnector
from .sap import MockSapConnector

_connectors: dict[str, ERPConnector] = {"sap": MockSapConnector(), "infor": MockInforConnector()}


def all_connectors() -> dict[str, ERPConnector]:
    return _connectors


def get_connector(name: str | None = None) -> ERPConnector:
    return _connectors[name or settings.erp_backend]
