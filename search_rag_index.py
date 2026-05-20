import streamlit as st
import logging
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Setup logging (centralized in main.py)
logger = logging.getLogger(__name__)
# RAG search UI supports querying Pulse private memory regulatory themes and 🛡️ security-relevant docs for Intel/CoS (search coordination)
# Pulse private memory + Shield (search rag index surface)

# Initialize embedding model
embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")

# Chroma database
CHROMA_PATH = "chroma_index"

def main():
    st.title("RAG File Search")
    
    # Initialize session state for pagination
    if 'results' not in st.session_state:
        st.session_state.results = []
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 0
    if 'total_results' not in st.session_state:
        st.session_state.total_results = 0
    
    query = st.text_input("Enter search query (e.g., '2024 budget notes'):")
    
    # Search configuration
    col1, col2 = st.columns(2)
    with col1:
        max_results = st.slider("Max results to fetch", min_value=10, max_value=100, value=20, step=10)
    with col2:
        results_per_page = st.slider("Results per page", min_value=5, max_value=20, value=10, step=5)
    
    if st.button("Search"):
        try:
            vector_store = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
            
            # Cap the search results to prevent UI overwhelm
            results = vector_store.similarity_search(query, k=max_results)
            
            st.session_state.results = results
            st.session_state.current_page = 0
            st.session_state.total_results = len(results)
            
            logger.info(f"Query '{query}' returned {len(results)} results (capped at {max_results})")
            
            if not results:
                st.write("No results found for the query")
                logger.warning(f"No results for query: {query}")
                
        except Exception as e:
            st.error(f"Search failed: {str(e)}")
            logger.error(f"Search error for query '{query}': {e}")
    
    # Display results with pagination
    if st.session_state.results:
        total_pages = (st.session_state.total_results + results_per_page - 1) // results_per_page
        start_idx = st.session_state.current_page * results_per_page
        end_idx = min(start_idx + results_per_page, st.session_state.total_results)
        
        st.write(f"Showing {start_idx + 1}-{end_idx} of {st.session_state.total_results} results")
        
        # Pagination controls
        if total_pages > 1:
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                if st.button("⏮️ First", disabled=st.session_state.current_page == 0):
                    st.session_state.current_page = 0
                    st.rerun()
            
            with col2:
                if st.button("◀️ Previous", disabled=st.session_state.current_page == 0):
                    st.session_state.current_page -= 1
                    st.rerun()
            
            with col3:
                st.write(f"Page {st.session_state.current_page + 1} of {total_pages}")
            
            with col4:
                if st.button("Next ▶️", disabled=st.session_state.current_page >= total_pages - 1):
                    st.session_state.current_page += 1
                    st.rerun()
            
            with col5:
                if st.button("Last ⏭️", disabled=st.session_state.current_page >= total_pages - 1):
                    st.session_state.current_page = total_pages - 1
                    st.rerun()
        
        # Display current page results
        for i in range(start_idx, end_idx):
            doc = st.session_state.results[i]
            with st.expander(f"Result {i+1}: {doc.metadata.get('source', 'unknown')}", expanded=False):
                st.write("**Content:**")
                st.write(doc.page_content)
                st.write("**Metadata:**")
                st.json(doc.metadata)
                logger.info(f"Result {i+1}: {doc.metadata.get('source', 'unknown')} - {doc.page_content[:100]}")
        
        # Show summary statistics
        st.info(f"📊 Search completed successfully. Found {st.session_state.total_results} results for query: '{query}'")

if __name__ == "__main__":
    main()