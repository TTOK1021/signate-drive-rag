# evaluation ディレクトリ構成

## 全体構成

```text
evaluation/
├─ data/
│  └─ valid_txt.csv
├─ src/
│  ├─ dbmanager.py
│  ├─ evaluator.py
│  ├─ settings.py
│  └─ validator.py
├─ submit/
│  └─ predictions.csv
├─ crag.py
├─ docker-compose.yml
├─ Dockerfile
└─ readme.md
```

## 直下ファイル・フォルダ

| パス | 種別 | 概要 |
| --- | --- | --- |
| `evaluation/data/` | フォルダ | 評価用データを格納 |
| `evaluation/src/` | フォルダ | 評価・検証処理の Python ソースを格納 |
| `evaluation/submit/` | フォルダ | 提出・予測結果ファイルを格納 |
| `evaluation/crag.py` | ファイル | 評価実行に関係する Python スクリプト |
| `evaluation/docker-compose.yml` | ファイル | Docker Compose 設定 |
| `evaluation/Dockerfile` | ファイル | 評価環境用 Docker イメージ定義 |
| `evaluation/readme.md` | ファイル | evaluation フォルダの説明ドキュメント |

## data

```text
evaluation/data/
└─ valid_txt.csv
```

| ファイル | 概要 |
| --- | --- |
| `valid_txt.csv` | 評価・検証用の CSV データ |

## src

```text
evaluation/src/
├─ dbmanager.py
├─ evaluator.py
├─ settings.py
└─ validator.py
```

| ファイル | 概要 |
| --- | --- |
| `dbmanager.py` | データベース管理に関係する処理 |
| `evaluator.py` | 評価処理 |
| `settings.py` | 評価処理で利用する設定 |
| `validator.py` | 入力・出力形式などの検証処理 |

## submit

```text
evaluation/submit/
└─ predictions.csv
```

| ファイル | 概要 |
| --- | --- |
| `predictions.csv` | 予測結果・提出用 CSV |
