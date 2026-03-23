import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from google import genai
import json
import os
from dotenv import load_dotenv


# PAGE CONFIG 
st.set_page_config(
    page_title="Business Intelligence Dashboard",
    page_icon="📊",
    layout="wide"
)

# LOAD CSS 
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css("style.css")

st.markdown("""
<style>
[data-testid="stToolbar"] {display: none;}
footer {visibility: hidden;}
#MainMenu {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# SESSION STATE 
if "messages" not in st.session_state:
    st.session_state.messages = []

# LOAD API KEY 
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

# HEADER
st.title("📊 Business Intelligence Dashboard")
st.markdown("""
Ask questions about your dataset and the system will automatically:

• Generate SQL queries  
• Analyze the data  
• Build visualizations  
""")

# SIDEBAR 
st.sidebar.title("Dataset Controls")

uploaded_file = st.sidebar.file_uploader(
    "Upload CSV Dataset (optional)",
    type=["csv"]
)

# Clear chat
if st.sidebar.button("Clear Chat"):
    st.session_state.messages = []
    st.rerun()


# DATASET LOADING 
if uploaded_file is not None:

    df_uploaded = pd.read_csv(uploaded_file, encoding="latin1")

    df_uploaded = df_uploaded.loc[:, ~df_uploaded.columns.str.contains("webresource", case=False)]

    df_uploaded.columns = df_uploaded.columns.str.strip()
    df_uploaded.columns = df_uploaded.columns.str.replace(r'[^\w\s]', '', regex=True)
    df_uploaded.columns = df_uploaded.columns.str.replace(" ", "_")
    df_uploaded.columns = df_uploaded.columns.str.lower()

    df_uploaded = df_uploaded.dropna(how="all")

    conn = sqlite3.connect(":memory:")
    df_uploaded.to_sql("data", conn, index=False, if_exists="replace")

    dataset_name = "data"
    columns = ", ".join(df_uploaded.columns)
    valid_columns = list(df_uploaded.columns)

    total_rows = len(df_uploaded)
    df_preview = df_uploaded.head(10)

    st.sidebar.info("Using uploaded dataset")
    st.toast("Dataset cleaned and loaded successfully")

else:

    conn = sqlite3.connect("customers.db")
    df_all = pd.read_sql_query("SELECT * FROM customers", conn)

    df_all = df_all.loc[:, ~df_all.columns.str.contains("webresource", case=False)]

    total_rows = len(df_all)
    df_preview = df_all.head(10)

    dataset_name = "customers"
    columns = ", ".join(df_all.columns)
    valid_columns = list(df_all.columns)

    st.sidebar.info("Using default dataset")


# DATASET INFO
st.subheader("Dataset Information")

col1, col2 = st.columns(2)
col1.metric("Rows", total_rows)
col2.metric("Columns", len(df_preview.columns))


# DATASET PREVIEW
st.subheader("Dataset Preview")
st.caption("Showing first 10 rows of the dataset")
st.dataframe(df_preview, width="stretch")

st.divider()
st.info("💡 Ask questions below to explore insights from the dataset.")
st.divider()


# GEMINI CACHE
@st.cache_data(ttl=3600)
def ask_gemini(prompt):
    return client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )


# DATABASE QUERY
@st.cache_data
def run_query(sql_query):
    return pd.read_sql_query(sql_query, conn)


# CHAT HISTORY DISPLAY
for i, message in enumerate(st.session_state.messages):

    with st.chat_message(message["role"]):

        if message["type"] == "text":
            st.write(message["content"])

        elif message["type"] == "data":
            st.dataframe(message["content"], width="stretch")

        elif message["type"] == "chart":
            st.plotly_chart(
                message["content"],
                width="stretch",
                key=f"history_chart_{i}"
            )

        elif message["type"] == "metric":
            st.metric(message["label"], message["value"])


# INPUT
prompt = st.chat_input("Ask a question about your dataset")

if prompt:

    st.session_state.messages.append({
        "role": "user",
        "type": "text",
        "content": prompt
    })

    with st.chat_message("user"):
        st.write(prompt)

    history = " ".join(
        msg["content"] for msg in st.session_state.messages if msg["role"] == "user"
    )


# GENERATE SQL + CHART
    with st.spinner("Analyzing data with AI..."):

        response = ask_gemini(f"""
You are a data analyst.

Database table: {dataset_name}

Available columns:
{columns}

Conversation history:
{history}

Current user question:
{prompt}

IMPORTANT RULES:
- Only use columns listed above.
- Do NOT invent column names.
- If the requested column does not exist return an error.
- Use ONLY SQLite compatible SQL
- DO NOT use ILIKE
- Use LOWER(column) LIKE '%value%' for case-insensitive text search

Chart selection rules:
- bar → category comparison
- pie → distribution
- line → trends over time
- histogram → distribution of a single numeric column
- scatter → relationship between two numeric variables
- area → cumulative trend
- metric → single value

Return ONLY JSON.

{{
"sql":"SQL_QUERY",
"chart":"bar|pie|line|histogram|scatter|area|metric"
}}
""")

    text = response.text.strip()
    json_text = text[text.find("{"):text.rfind("}")+1]
    result = json.loads(json_text)


# ERROR HANDLING
    if "error" in result:

        with st.chat_message("assistant"):
            st.error(result["error"])

        st.session_state.messages.append({
            "role":"assistant",
            "type":"text",
            "content":result["error"]
        })

        st.stop()


    sql = result.get("sql")
    chart = result.get("chart", "bar")


# SQL SAFETY FIX
    if "ILIKE" in sql:
        sql = sql.replace("ILIKE", "LIKE")
        st.warning("Adjusted query for SQLite compatibility")

    for col in valid_columns:
        sql = sql.replace(f"{col} LIKE", f"LOWER({col}) LIKE")
        sql = sql.replace(f"{col.lower()} LIKE", f"LOWER({col}) LIKE")


    df = run_query(sql)

    

# RESPONSE
    with st.chat_message("assistant"):

        st.code(sql)

        if df.empty:
            st.warning("Query returned no results")

        else:

            st.subheader("Query Result")
            st.dataframe(df, width="stretch")

            st.session_state.messages.append({
                "role":"assistant",
                "type":"data",
                "content":df
            })


# METRIC
            if df.shape[1] == 1 or chart == "metric":

                st.metric(df.columns[0], df.iloc[0,0])

                st.session_state.messages.append({
                    "role":"assistant",
                    "type":"metric",
                    "label":df.columns[0],
                    "value":df.iloc[0,0]
                })


# CHART
            else:

                st.subheader("Visualization")

                if chart == "bar":
                    fig = px.bar(df, x=df.columns[0], y=df.columns[1])

                elif chart == "pie":
                    fig = px.pie(df, names=df.columns[0], values=df.columns[1])

                elif chart == "line":
                    fig = px.line(df, x=df.columns[0], y=df.columns[1])

                elif chart == "histogram":
                    fig = px.histogram(df, x=df.columns[0])

                elif chart == "scatter":
                    if len(df.columns) >= 2:
                        fig = px.scatter(df, x=df.columns[0], y=df.columns[1])
                    else:
                        st.warning("Scatter plot requires at least 2 columns")
                        st.stop()

                elif chart == "area":
                    fig = px.area(df, x=df.columns[0], y=df.columns[1])

                else:
                    fig = px.bar(df, x=df.columns[0], y=df.columns[1])

                st.plotly_chart(
                    fig,
                    width="stretch",
                    key=f"new_chart_{len(st.session_state.messages)}"
                )

                st.session_state.messages.append({
                    "role":"assistant",
                    "type":"chart",
                    "content":fig
                })