"""pytest 설정: src/ 디렉토리를 모듈 검색 경로에 추가."""

import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "src"))
