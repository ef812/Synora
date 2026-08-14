from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectorstore = Chroma(persist_directory="db", embedding_function=embedding_model)

print("Collection count:", vectorstore._collection.count())

docs = vectorstore.similarity_search("dizzy tired", k=4)
print("Docs found:", len(docs))
for d in docs:
    print(d.metadata, d.page_content[:100])