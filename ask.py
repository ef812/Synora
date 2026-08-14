from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from ollama import chat

print("Loading embeddings...")
embeddings = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2"
)

print("Loading database...")
db = Chroma(
    persist_directory="db",
    embedding_function=embeddings
)

while True:
    question = input("\nAsk: ")

    if question.lower() == "exit":
        break

    print("Searching...")

    try:
        docs = db.similarity_search(question, k=3)
        print("Number of docs:", len(docs))
        print("Found", len(docs), "documents")
        print("\n========== DOCUMENT METADATA ==========\n")

        for doc in docs:
            print(doc.metadata)

        print("\n=======================================\n")

        context = "\n\n".join(
            [doc.page_content for doc in docs]
)

    except Exception as e:
        print("ERROR DURING SEARCH:")
        print(e)
        continue

    print("\n========== RETRIEVED CONTEXT ==========\n")
    print(context)
    print("\n=======================================\n")
    print("Sending to Qwen...")

    prompt = f"""
You are a medical assistant.

You MUST follow these rules:

1. Answer ONLY using the information in the Context.
2. Do NOT use your own knowledge.
3. If the answer is not found in the Context, reply exactly:

I don't know based on the provided documents.

4. If possible, quote or closely follow the wording from the Context.

====================
CONTEXT
====================

{context}

====================
QUESTION
====================

{question}

====================
ANSWER
====================
"""

    try:
        response = chat(
            model="qwen3:1.7b",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        print("\nAnswer:")
        print(response["message"]["content"])
        print("\n========== REFERENCES ==========\n")

        for doc in docs:
           source = doc.metadata.get("source", "Unknown")
           page = doc.metadata.get("page", 0) + 1

        print(f"{source} | Page {page}")

        print("\n================================\n")

    except Exception as e:
        print("ERROR:")
        print(e)