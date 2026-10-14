"""Strict inputs and non-overwriting JSON reports."""
import json
import math
from pathlib import Path

def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result

def constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")

def loads(text):
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)

def load(path, limit=64 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Input exceeds 64 MiB limit.")
    return loads(raw.decode("utf-8-sig"))

def integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    return value

def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite.")
    try:
        parsed = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite.")
    return parsed

def text(value, name):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be a nonempty string without control characters.")
    return value

def emit(report, output=None):
    encoded = json.dumps(report, ensure_ascii=not bool(output), allow_nan=False, indent=2) + "\n"
    if output:
        with Path(output).open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    else:
        print(encoded, end="")

def code(report, strict=False):
    return int(report.get("error_count", 0) > 0 or (strict and report.get("warning_count", 0) > 0))

class Findings:
    def __init__(self):
        self.items = []
        self.counts = {}
        self.severity_counts = {"error": 0, "warning": 0}
    def add(self, code, severity, message, **context):
        self.counts[code] = self.counts.get(code, 0) + 1
        self.severity_counts[severity] += 1
        if len(self.items) < 200:
            self.items.append(dict(code=code, severity=severity, message=message, **context))
    def report(self):
        return {"findings": self.items, "finding_counts": self.counts,
                "error_count": self.severity_counts["error"], "warning_count": self.severity_counts["warning"],
                "findings_truncated": sum(self.counts.values()) > len(self.items)}
