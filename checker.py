#!/usr/bin/env python3
"""Dependency-free recheck of weighted-quantile-audit/v1 witnesses.

The mathematical checks use direct sums on the original observations, not the
producer's sorting/aggregation oracle. Saved float diagnostics are checked for
internal consistency; this does not authenticate a library call. Use the pinned
observation replay to verify library provenance and outputs independently.
"""
from bisect import bisect_left
from fractions import Fraction as F
import argparse
import json
import math
from pathlib import Path
import re
import sys

MAX_BYTES = 2 * 1024 * 1024
RATIONAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def object_(value, label):
    need(type(value) is dict, label + " must be an object")
    return value


def rational(value, label, bits=8192, length=4096):
    need(type(value) is str and len(value) <= length, label + " must be a bounded rational string")
    need(RATIONAL.fullmatch(value) is not None, label + " has invalid rational syntax")
    q = F(value)
    need(str(q) == value, label + " must be canonical")
    need(max(q.numerator.bit_length(), q.denominator.bit_length()) <= bits, label + " exceeds bit limit")
    return q


def hexfloat(value, label):
    need(type(value) is str and len(value) <= 32, label + " must be a float.hex string")
    number = float.fromhex(value)
    need(math.isfinite(number) and number.hex() == value, label + " must be canonical finite float.hex")
    return number


def check_bool(actual, expected, label):
    need(type(actual) is bool and actual is expected, label + " is incorrect")


def parse_input(value, label, nominal):
    data = object_(value, label)
    need(set(data) == {"x", "w", "p"}, label + " requires x,w,p only")
    need(type(data["x"]) is list and type(data["w"]) is list, label + " x,w must be arrays")
    need(1 <= len(data["x"]) <= 16 and len(data["x"]) == len(data["w"]), label + " invalid lengths")
    bits, length = (128, 96) if nominal else (256, 192)
    x = [rational(v, label + ".x", bits, length) for v in data["x"]]
    w = [rational(v, label + ".w", bits, length) for v in data["w"]]
    p = rational(data["p"], label + ".p", bits, length)
    need(all(v > 0 for v in w) and 0 < p < 1, label + " needs positive weights and interior p")
    return x, w, p


def check_certificate(cert, x, w, p, definition, label):
    cert = object_(cert, label)
    need(set(cert) == {"kind", "left", "right", "L", "U", "target", "W", "value"}, label + " has incorrect fields")
    left = rational(cert["left"], label + ".left")
    need(left in x, label + ".left is not a support point")
    total = sum(w, F(0))
    target = p * total
    lower = sum((weight for value, weight in zip(x, w) if value < left), F(0))
    upper = sum((weight for value, weight in zip(x, w) if value <= left), F(0))
    for key, expected in (("W", total), ("target", target), ("L", lower), ("U", upper)):
        need(rational(cert[key], label + "." + key) == expected, label + "." + key + " disagrees with direct sum")
    if cert["kind"] == "point":
        need(cert["right"] is None and lower < target < upper, label + " point requires L<t<U and null right")
        expected = left
    elif cert["kind"] == "tie":
        right = rational(cert["right"], label + ".right")
        need(lower < target == upper, label + " tie requires L<t=U")
        need(right in x and right > left, label + " invalid right support")
        need(not any(left < v < right for v in x), label + " right is not adjacent")
        expected = (left + right) / 2 if definition == "boundary_average" else left
    else:
        raise ValueError(label + " invalid kind")
    need(rational(cert["value"], label + ".value") == expected, label + " incorrect value")
    return expected


def validate(document):
    """Return a check receipt; raise ValueError for a malformed/invalid witness."""
    try:
        return _validate(document)
    except (KeyError, IndexError, TypeError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError("malformed witness: " + type(exc).__name__) from exc


def _validate(document):
    doc = object_(document, "document")
    need(doc.get("schema") == "weighted-quantile-audit/v1" and doc.get("status") == "OK", "unsupported witness schema/status")
    nominal = parse_input(doc["nominal_input"], "nominal_input", True)
    binary = parse_input(doc["binary_input"], "binary_input", False)
    hex_input = object_(doc["hex_input"], "hex_input")
    need(set(hex_input) == {"x", "w", "p"}, "hex_input requires x,w,p only")
    changed = []
    for index, key in enumerate(("x", "w")):
        need(type(hex_input[key]) is list and len(hex_input[key]) == len(nominal[index]), "hex_input invalid length")
        need(len(binary[index]) == len(nominal[index]), "binary input invalid length")
        for j, (a, b, h) in enumerate(zip(nominal[index], binary[index], hex_input[key])):
            rounded = float(a)
            need(F(rounded) == b and hexfloat(h, "hex_input." + key) == rounded and h == rounded.hex(), "nominal/binary/hex binding failed")
            if a != b:
                changed.append(f"{key}[{j}]")
    rounded_p = float(nominal[2])
    need(F(rounded_p) == binary[2] and hex_input["p"] == rounded_p.hex(), "nominal/binary/hex probability binding failed")
    hexfloat(hex_input["p"], "hex_input.p")
    if nominal[2] != binary[2]:
        changed.append("p")
    rounding = object_(doc["input_rounding"], "input_rounding")
    need(rounding["changed_fields"] == changed, "changed_fields incorrect")

    certificates = object_(doc["certificates"], "certificates")
    need(set(certificates) == {"nominal", "binary"}, "need nominal and binary certificates")
    values = {}
    for label, inp in (("nominal", nominal), ("binary", binary)):
        pair = object_(certificates[label], "certificates." + label)
        need(set(pair) == {"boundary_average", "inverted_cdf"}, "need both definitions")
        for definition in ("boundary_average", "inverted_cdf"):
            values[label, definition] = check_certificate(pair[definition], *inp, definition, label + "." + definition)

    observed = object_(doc["observed"], "observed")
    actual = hexfloat(observed["value_hex"], "observed.value_hex")
    expected = float(values["binary", "boundary_average"])
    need(observed["expected_hex"] == expected.hex(), "observed.expected_hex incorrect")
    expected_axes = {
        "definition_difference": values["binary", "boundary_average"] != values["binary", "inverted_cdf"],
        "input_rounding_changes_value": values["nominal", "boundary_average"] != values["binary", "boundary_average"],
        "implementation_value_mismatch": expected != actual,
    }
    axes = object_(doc["axes"], "axes")
    need(set(axes) == set(expected_axes), "axes fields incorrect")
    for key, value in expected_axes.items():
        check_bool(axes[key], value, "axes." + key)

    x, w, p = binary
    supports = sorted(set(x))
    candidates = ["point:" + str(v) for v in supports if float(v) == actual]
    candidates += ["tie:" + str(a) + "," + str(b) for a, b in zip(supports, supports[1:]) if (float(a) + float(b)) / 2 == actual]
    branch = candidates[0] if len(candidates) == 1 else "BRANCH_UNKNOWN"
    need(observed["branch_candidates"] == candidates, "branch_candidates incorrect")
    need(observed["branch_identification"] == branch, "branch_identification incorrect")

    arithmetic = object_(doc["arithmetic"], "arithmetic")
    need(arithmetic["support"] == list(map(str, supports)), "arithmetic support incorrect")
    saved_cumulative = arithmetic["cumulative_hex"]
    need(type(saved_cumulative) is list and len(saved_cumulative) == len(supports), "cumulative length incorrect")
    cumulative = [hexfloat(v, "cumulative_hex") for v in saved_cumulative]
    need(cumulative[0] > 0 and all(a <= b for a, b in zip(cumulative, cumulative[1:])), "cumulative must be positive nondecreasing")
    target = hexfloat(arithmetic["target_hex"], "target_hex")
    need(arithmetic["target_hex"] == (float(p) * cumulative[-1]).hex(), "float target does not equal p*saved total")
    selected = bisect_left(cumulative, target)
    need(selected < len(cumulative), "target beyond saved cumulative")
    need(type(arithmetic["selected_index"]) is int and arithmetic["selected_index"] == selected, "selected_index incorrect")
    gap = abs(target - cumulative[selected])
    need(arithmetic["gap_hex"] == gap.hex(), "gap_hex incorrect")
    need(arithmetic["tolerance_hex"] == float(1e-10).hex(), "fixed tolerance changed")
    hit = gap < 1e-10
    successor = selected + 1 < len(supports)
    check_bool(arithmetic["tolerance_hit"], hit, "tolerance_hit")
    check_bool(arithmetic["has_successor"], successor, "has_successor")
    cumulative_exact = all(F(c) == sum((weight for value, weight in zip(x, w) if value <= bound), F(0)) for c, bound in zip(cumulative, supports))
    target_exact = F(target) == p * sum(w, F(0))
    check_bool(arithmetic["cumulative_exact"], cumulative_exact, "cumulative_exact")
    check_bool(arithmetic["target_exact"], target_exact, "target_exact")
    predicted = (float(supports[selected]) + float(supports[selected + 1])) / 2 if hit and successor else float(supports[selected])
    need(arithmetic["predicted_hex"] == predicted.hex(), "predicted_hex incorrect")
    matches = predicted == actual
    check_bool(arithmetic["matches_observed"], matches, "matches_observed")
    if not expected_axes["implementation_value_mismatch"]:
        diagnosis = "NO_VALUE_MISMATCH"
    elif cumulative_exact and target_exact and gap != 0 and hit and successor and matches and branch != "BRANCH_UNKNOWN":
        diagnosis = "TOLERANCE_ONLY_WITNESS"
    elif not (cumulative_exact and target_exact):
        diagnosis = "ARITHMETIC_ROUNDING_PRESENT"
    else:
        diagnosis = "UNRESOLVED"
    need(doc["implementation_diagnosis"] == diagnosis, "implementation_diagnosis incorrect")
    return {"valid": True, "certificates": 4,
            "checks": ["input_domain", "nominal_binary_hex_binding", "four_exact_certificates", "three_axes", "branch_value_candidates", "diagnostic_consistency"],
            "scope": "mathematics_and_saved_diagnostic_consistency; library_authenticity_requires_replay"}


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="-", help="witness JSON, or stdin")
    args = parser.parse_args()
    try:
        if args.path == "-":
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        else:
            with Path(args.path).open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        need(len(raw) <= MAX_BYTES, "witness exceeds 2 MiB")
        document = json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=reject_constant)
        receipt = validate(document)
    except (ValueError, OSError, RecursionError, UnicodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
