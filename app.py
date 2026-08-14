import os
import streamlit as st
from langchain_groq import ChatGroq
from langchain_community.llms import Ollama
from langchain_core.messages import HumanMessage, SystemMessage

from guardrails import is_safe_query, clean_sql_query
from db_connector import execute_query
from prompts import SYSTEM_PROMPT, CONSULTANT_PROMPT_TEMPLATE

# --- Page Config ---
st.set_page_config(
    page_title="RailPulse AI | Station Manager Co-Pilot",
    page_icon="🚉",
    layout="wide"
)

st.title("🚉 RailPulse AI: Operational Assistant")
st.caption("Intelligent GTFS Transit Analytics & Conversational Insights for SNCB/NMBS")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("⚙️ Provider Settings")
    provider = st.radio("LLM Backend", ["Groq (Cloud Free API)", "Ollama (Local)"])
    
    if provider == "Groq (Cloud Free API)":
        api_key = st.text_input("Groq API Key", type="password", value=os.getenv("GROQ_API_KEY", ""))
        model_name = st.selectbox("Model", ["llama-3.1-8b-instant", "llama3-70b-8096", "mixtral-8x7b-32768"])
    else:
        ollama_url = st.text_input("Ollama URL", value="http://localhost:11434")
        model_name = st.text_input("Local Model", value="llama3")

# --- LLM Initialization ---
def get_llm():
    if provider == "Groq (Cloud Free API)":
        if not api_key:
            st.error("Please enter a valid Groq API Key.")
            st.stop()
        return ChatGroq(groq_api_key=api_key, model_name=model_name, temperature=0.0)
    else:
        return Ollama(base_url=ollama_url, model=model_name, temperature=0.0)

# --- Chat Interface ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# User Input
if user_prompt := st.chat_input("Ask about stations, schedules, routes, or delays..."):
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Generating SQL query..."):
            try:
                llm = get_llm()
                
                # 1. Generate SQL Query
                messages = [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt)
                ]
                raw_sql_response = llm.invoke(messages)
                raw_sql = raw_sql_response.content if hasattr(raw_sql_response, 'content') else str(raw_sql_response)
                
                sql_query = clean_sql_query(raw_sql)
                
                # Render generated query block
                st.markdown("**Generated Query:**")
                st.code(sql_query, language="sql")

                # 2. Safety Check
                is_safe, reason = is_safe_query(sql_query)
                if not is_safe:
                    st.error(f"🛑 Security Interception: {reason}")
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": f"Security Alert: Query blocked. Reason: {reason}"
                    })
                else:
                    # 3. Database Execution
                    df_results = execute_query(sql_query)
                    
                    if df_results.empty:
                        st.warning("No records returned for this query.")
                        response_text = "No records were found matching your query criteria."
                    else:
                        st.markdown("**Query Results:**")
                        st.dataframe(df_results, use_container_width=True)

                        # 4. Generate Tactical Advice
                        consultant_prompt = CONSULTANT_PROMPT_TEMPLATE.format(
                            user_query=user_prompt,
                            sql_query=sql_query,
                            query_data=df_results.head(10).to_markdown(index=False)
                        )
                        
                        raw_advice = llm.invoke([HumanMessage(content=consultant_prompt)])
                        advice_text = raw_advice.content if hasattr(raw_advice, 'content') else str(raw_advice)
                        
                        st.markdown("---")
                        st.markdown("### 💡 RailPulse Tactical Briefing")
                        st.markdown(advice_text)
                        
                        response_text = advice_text

                    st.session_state.messages.append({"role": "assistant", "content": response_text})

            except Exception as e:
                st.error(f"An error occurred: {str(e)}")