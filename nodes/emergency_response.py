PHYSICAL_EMERGENCY_MESSAGE = (
    "This sounds like it could be a medical emergency. "
    "Please call your local emergency number right now (911 in the US, "
    "112 in the EU, or your country's equivalent) or go to the nearest "
    "emergency room immediately. I'm not able to help with urgent medical "
    "situations — please get in touch with emergency services right away."
)

CRISIS_MESSAGE = (
    "It sounds like you might be going through something really difficult "
    "right now. I want to make sure you get real support — please reach out "
    "to a crisis line right now:\n\n"
    "- US: 988 Suicide & Crisis Lifeline (call or text 988)\n"
    "- UK: Samaritans, 116 123\n"
    "- Or your local emergency number\n\n"
    "You don't have to go through this alone, and people are available to "
    "talk right now."
)


def emergency_response(state: dict) -> dict:
    if state["emergency_type"] == "physical":
        state["response"] = PHYSICAL_EMERGENCY_MESSAGE
    else:
        state["response"] = CRISIS_MESSAGE
    return state