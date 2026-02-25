import os
import sys
from pathlib import Path
from typing import List


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from wealthtax_agent.state import GraphState, Slip


os.environ.setdefault("GROQ_API_KEY", "gsk-test-key")


def make_state_with_slips(slips: List[Slip]) -> GraphState:
    return GraphState(raw_docs=[], slips=slips)
