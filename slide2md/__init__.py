"""PDF·PPTX 슬라이드를 페이지별 Markdown으로 바꾸는 로컬 도구."""
from .model import Options, Page, Result
from .convert import Cancelled, SUPPORTED, convert

__all__ = ["Options", "Page", "Result", "Cancelled", "SUPPORTED", "convert"]
__version__ = "0.1.0"
