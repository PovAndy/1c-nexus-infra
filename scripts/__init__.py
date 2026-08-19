"""1c-nexus-infra scripts package.

Добавляет каталог скриптов в sys.path, чтобы межмодульные импорты
(map_workspace_graph_v2, omvl_llm_runtime и др.) работали и как пакет
(pip install -e .), и при прямом запуске python3 scripts/<script>.py.
"""

import os
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
