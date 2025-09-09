import streamlit as st
import logging
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Setup logging
logging.basicConfig(filename='search.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize embedding model
embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")

# Chroma database
CHROMA_PATH = "chroma_index"

def main():
    st.title("RAG File Search")
    query = st.text_input("Enter search query (e.g., '2024 budget notes'):")
    if st.button("Search"):
        vector_store = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
        results = vector_store.similarity_search(query, k=500)
        logging.info(f"Query '{query}' returned {len(results)} results")
        if results:
            for i, doc in enumerate(results):
                st.write(f"Result {i+1}: {doc.metadata.get('source', 'unknown')} - {doc.page_content[:100]}")
                logging.info(f"Result {i+1}: {doc.metadata.get('source', 'unknown')} - {doc.page_content[:100]}")
        else:
            st.write("No results found for the query")
            logging.warning(f"No results for query: {query}")

if __name__ == "__main__":
    main()