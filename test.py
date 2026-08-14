from ollama import chat

while True:
    question = input("\nYou: ")

    if question.lower() == "exit":
        break

    response = chat(
        model='qwen3:1.7b',
        messages=[
            {
                'role': 'user',
                'content': question
            }
        ]
    )

    print("AI:", response['message']['content'])