import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "dags"))
