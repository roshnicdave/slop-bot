"""Deterministic pronunciation for technical labels; no extra model calls."""

import re


def number(n):
    small = [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
    ]
    tens = [
        "",
        "",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
    ]
    if n < 20:
        return small[n]
    if n < 100:
        return tens[n // 10] + (" " + small[n % 10] if n % 10 else "")
    return small[n // 100] + " hundred" + (" " + number(n % 100) if n % 100 else "")


def speak(text):
    text = re.sub(
        r"\b(\d{1,3}(?:\.\d{1,3}){3})\b",
        lambda m: " dot ".join(number(int(n)) for n in m[1].split(".")),
        text,
    )
    text = re.sub(r"/(\d{1,2})\b", lambda m: " slash " + number(int(m[1])), text)
    for old, new in [
        ("Layer 2", "Layer two"),
        ("Layer 3", "Layer three"),
        ("TTL", "T T L"),
        ("MTU", "M T U"),
        ("DHCP", "D H C P"),
        ("HTTPS", "H T T P S"),
        ("DNS", "D N S"),
        ("ARP", "arp"),
    ]:
        text = text.replace(old, new)
    return " ".join(text.split())
