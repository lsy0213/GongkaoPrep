"""资料整理的黄金样本回归检查（需要本机资料文件夹，约 40 秒）：pytest -m golden

改了 docs.py / docq.py / doccleanup.py / layout.py / pdftext.py 之后跑一遍；样本和基准见 tools/golden.py。
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import golden  # noqa: E402

pytestmark = pytest.mark.golden


def test_golden_samples():
    if not golden.EXPECTED.exists():
        pytest.skip("还没有登记基准：python tools/golden.py update")
    data_dir = os.environ.pop("GONGKAO_DATA_DIR", None)  # 读真实数据目录里的 catalog.json
    try:
        files, root = golden._files()
    finally:
        if data_dir:
            os.environ["GONGKAO_DATA_DIR"] = data_dir
    if not files:
        pytest.skip("本机没有资料文件夹或资料目录")
    problems = golden.compare(files, root)
    assert not problems, "\n\n".join(problems)
