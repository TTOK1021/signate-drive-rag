import os
import time
from typing import Any

import pandas as pd


class DBLoader:
    def __init__(self, db_path: str) -> None:
        """
        no header, index column=0
        """
        print("\nLoading Ground Truth:")
        start = time.time()
        self.db = pd.read_csv(db_path, index_col=0, header=None)
        print(f"  db shape: {self.db.shape}")
        print(f"  time elapsed: {time.time() - start}[s]")

    def get_db(self) -> pd.DataFrame:
        return self.db


class ResultHandler:
    def __init__(self, score: float, result: dict[str, Any], eval_result_dir: str) -> None:
        print("\nSaving the Results:")
        self.score = score
        self.result = result
        self.eval_result_dir = eval_result_dir

    def save(self):
        start = time.time()
        if not os.path.exists(self.eval_result_dir):
            os.mkdir(self.eval_result_dir)

        print(f"  Score: {self.score}")

        pd.DataFrame(self.result).T.to_csv(
            os.path.join(self.eval_result_dir, "scoring.csv"), header=False
        )

        print(f"  time elapsed: {time.time() - start}[s]")
