from graph import graph


def run(question: str, audience: str = "employee"):
    initial_state = {
        "question": question,
        "audience": audience,
        "sensor_data": {},
        "intent": "",
        "context": "",
        "sources": [],
        "pages": [],
        "analysis": None,
        "emergency_type": None,
        "recommendations": [],
        "evidence_check_passed": True,
        "evidence_failures": [],
        "response": "",
    }
    result = graph.invoke(initial_state)
    print("---- DEBUG STATE ----")
    print("intent:", result["intent"])
    print("sources:", result["sources"])
    print("analysis:", result["analysis"])
    print("evidence_check_passed:", result["evidence_check_passed"])
    print("evidence_failures:", result["evidence_failures"])
    print("recommendations:", result["recommendations"])
    print("----------------------")
    print(result["response"])


def ask_audience() -> str:
    options = {
        "1": "employee",
        "2": "doctor",   # covers doctor/nurse
        "3": "individual",
    }
    print("Who are you?")
    print("1. Employee")
    print("2. Doctor/Nurse")
    print("3. Individual")

    while True:
        choice = input("Select an option (1-3): ").strip()
        if choice in options:
            return options[choice]
        print("Invalid choice, please enter 1, 2, or 3.")


if __name__ == "__main__":
    question = input("Ask Synora a health question: ")
    audience = ask_audience()
    run(question, audience)