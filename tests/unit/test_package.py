"""パッケージ基本情報のテスト。"""

import signate_drive_rag


def test_package_version() -> None:
    """パッケージのバージョンが定義されていることを確認する。"""
    assert signate_drive_rag.__version__ == "0.1.0"
