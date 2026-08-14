import re

# Patterns for acute physical emergencies
PHYSICAL_EMERGENCY_PATTERNS = [
    r"\bchest pain\b", r"\bcan'?t breathe\b", r"\btrouble breathing\b",
    r"\bsevere bleeding\b", r"\bunconscious\b", r"\bnot breathing\b",
    r"\bstroke\b", r"\bheart attack\b", r"\bseizure\b",
    r"\boverdose\b", r"\bpoison(ed|ing)?\b", r"\banaphyla",
]

# Patterns for mental health crisis / self-harm risk
CRISIS_PATTERNS = [
    r"\bsuicid", r"\bkill(ing)? myself\b", r"\bend(ing)?\s+(it all|my life)\b",
    r"\bself[\s-]?harm\b", r"\bwant(ed)? to die\b", r"\bhurt(ing)? myself\b",
    r"\bcan'?t (go on|do this anymore|take it anymore)\b",
    r"\bno reason to live\b", r"\bbetter off (dead|without me)\b",
    r"\bthinking about (ending|suicide|killing myself)\b",
    r"\boverwhelmed\b", r"\bhopeless\b", r"\bgiving up\b",
    r"\bworthless\b", r"\bcan'?t cope\b",
]


def check_emergency(state: dict) -> dict:
    text = state["question"].lower()

    is_physical = any(re.search(p, text) for p in PHYSICAL_EMERGENCY_PATTERNS)
    is_crisis = any(re.search(p, text) for p in CRISIS_PATTERNS)

    state["emergency_type"] = (
        "physical" if is_physical else
        "crisis" if is_crisis else
        None
    )
    return state