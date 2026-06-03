"""Taipei-only attraction search platform client."""

from .core.models import Place, SearchQuery, SearchResult
from .services.search_service import TaipeiAttractionSearchService

__all__ = ["Place", "SearchQuery", "SearchResult", "TaipeiAttractionSearchService"]
__version__ = "1.0.0"
