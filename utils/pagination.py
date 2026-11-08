"""
utils/pagination.py
Reusable pagination helper for long data tables across AI Campus Placement Agent.
Provides page navigation, record counts, active filter preservation, and JSON metadata.
"""

import math
from typing import Sequence, TypeVar, List, Dict, Any, Optional
from urllib.parse import urlencode

T = TypeVar("T")


class Pagination:
    """
    Pagination calculator and URL builder for tabular lists and card grids.
    Supports both client-side and server-side slicing, empty list protection,
    and query string retention for filter preserving navigation.
    """

    def __init__(
        self,
        items: Sequence[T],
        page: int = 1,
        per_page: int = 10,
        total: Optional[int] = None,
        endpoint_args: Optional[Dict[str, Any]] = None,
        base_url: str = "",
    ):
        """
        Initializes pagination state.

        Args:
            items: Full list of items (sliced by page) OR pre-sliced items when total is passed.
            page: Requested 1-indexed page number.
            per_page: Number of records per page (minimum 1, default 10).
            total: Total record count across all pages (optional).
            endpoint_args: Active query parameters to preserve across page transitions.
            base_url: Base endpoint URL string.
        """
        try:
            self.per_page = max(1, int(per_page))
        except (ValueError, TypeError):
            self.per_page = 10

        self.total_records = len(items) if total is None else max(0, int(total))
        self.total_pages = max(1, math.ceil(self.total_records / self.per_page)) if self.total_records > 0 else 1

        try:
            req_page = int(page)
        except (ValueError, TypeError):
            req_page = 1

        if req_page < 1:
            self.page = 1
        elif self.total_records > 0 and req_page > self.total_pages:
            self.page = self.total_pages
        else:
            self.page = max(1, req_page)

        # Slice items if un-sliced full list was provided
        if total is None:
            start_idx = (self.page - 1) * self.per_page
            end_idx = start_idx + self.per_page
            self.items = list(items[start_idx:end_idx])
        else:
            self.items = list(items)

        self.has_prev = self.page > 1
        self.has_next = self.page < self.total_pages
        self.prev_page = self.page - 1 if self.has_prev else None
        self.next_page = self.page + 1 if self.has_next else None

        if self.total_records == 0:
            self.start_index = 0
            self.end_index = 0
        else:
            self.start_index = (self.page - 1) * self.per_page + 1
            self.end_index = min(self.page * self.per_page, self.total_records)

        # Retain search & filter parameters, discarding 'page' to avoid parameter collisions
        self.endpoint_args: Dict[str, Any] = {}
        if endpoint_args:
            for k, v in endpoint_args.items():
                if k != "page" and v is not None and v != "":
                    self.endpoint_args[k] = v

        self.base_url = base_url

    def url_for_page(self, page_num: int) -> str:
        """
        Constructs a URL string pointing to page_num while retaining
        all active search queries, dropdown filters, and sorting choices.
        """
        params = dict(self.endpoint_args)
        params["page"] = page_num
        query_string = urlencode(params, doseq=True)
        sep = "&" if "?" in self.base_url else "?"
        return f"{self.base_url}{sep}{query_string}" if self.base_url else f"?{query_string}"

    def page_range(self, max_visible: int = 5) -> List[Optional[int]]:
        """
        Produces a smart list of page numbers with ellipsis (None represents '...')
        for rendering desktop and tablet pagination bars.
        e.g. [1, 2, 3, 4, 5] or [1, None, 4, 5, 6, None, 10]
        """
        if self.total_pages <= max_visible + 2:
            return list(range(1, self.total_pages + 1))

        pages: List[Optional[int]] = []
        half = max_visible // 2
        start = max(1, self.page - half)
        end = min(self.total_pages, start + max_visible - 1)

        if end - start < max_visible - 1:
            start = max(1, end - max_visible + 1)

        if start > 1:
            pages.append(1)
            if start > 2:
                pages.append(None)

        for p in range(start, end + 1):
            pages.append(p)

        if end < self.total_pages:
            if end < self.total_pages - 1:
                pages.append(None)
            pages.append(self.total_pages)

        return pages

    def to_dict(self) -> Dict[str, Any]:
        """Serializes pagination metadata into a dictionary for JSON API responses."""
        return {
            "page": self.page,
            "per_page": self.per_page,
            "total_records": self.total_records,
            "total_pages": self.total_pages,
            "has_prev": self.has_prev,
            "has_next": self.has_next,
            "prev_page": self.prev_page,
            "next_page": self.next_page,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "count": len(self.items),
        }

