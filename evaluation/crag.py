import argparse
import os

from src.dbmanager import DBLoader, ResultHandler
from src.evaluator import CRAGEvaluator
from src.settings import FormatSetter
from src.validator import DataFrameValidator


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", default="gpt-5.2-2025-12-11")
    parser.add_argument("--result-dir", default="./submit")
    parser.add_argument("--result-name", default="predictions.csv")
    parser.add_argument("--max-num-tokens", default=1000, type=int)
    parser.add_argument("--ans-dir", default="./data")
    parser.add_argument("--ans-txt", default="valid_txt.csv")
    parser.add_argument("--eval-result-dir", default="./result")
    args = parser.parse_args()

    return args


def main():
    # parse args
    args = parse_args()
    ans_txt_path = os.path.join(args.ans_dir, args.ans_txt)
    result_path = os.path.join(args.result_dir, args.result_name)

    # format settings
    data_format = FormatSetter(
        ans_txt_path=ans_txt_path,
        max_num_tokens=args.max_num_tokens,
        keys={},
        ext=".csv",
        model=args.model_name,
    ).get_format()

    # validation
    validator = DataFrameValidator(data_format=data_format)
    validator.validate(result=result_path)
    sub = validator.get_data()

    # load the answer texts
    ans = DBLoader(db_path=ans_txt_path).get_db()

    # evaluation
    score, result = CRAGEvaluator(sub=sub, ans=ans).evaluate(args.model_name)

    # save the results
    ResultHandler(score=score, result=result, eval_result_dir=args.eval_result_dir).save()


if __name__ == "__main__":
    main()
