import argparse
import json

from tradeoff.feedback.demo import run_feedback_demo

parser = argparse.ArgumentParser(description="Synthetic local agent-feedback example; no account or model needed")
parser.add_argument("--output", default="feedback-output-agent")
args = parser.parse_args()
print(json.dumps(run_feedback_demo(args.output), indent=2))
