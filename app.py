import os
import json
import time
import pandas as pd
import streamlit as st
from neo4j import GraphDatabase
from streamlit_agraph import agraph, Node, Edge, Config
from path_gen import generate_suggested_path
import tempfile
import streamlit.components.v1 as components
from neo4j_viz.neo4j import from_neo4j
from neo4j_viz.colors import ColorSpace
from palettable.wesanderson import Moonrise1_5

st.set_page_config(
    layout="wide",  # wide mode stretches content across the browser
    initial_sidebar_state="expanded"
)

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(
        st.secrets["NEO4J_URI"],
        auth=(st.secrets["NEO4J_USERNAME"], st.secrets["NEO4J_PASSWORD"])
    )

driver = get_driver()

@st.cache_data
def load_concentrations(csv_path="concentrations.csv"):
    df = pd.read_csv(csv_path)
    return df["Concentration"].dropna().tolist()

@st.cache_data
def load_courses(csv_path="courses.csv"):
    df = pd.read_csv(csv_path)
    return df["course_name"].dropna().tolist()

sample_query_flmb_requirements = """
MATCH (n)-[r:flmb_requirement]->(b)
RETURN n, r, b
""".strip() 

sample_query_econ_and_finance = """
MATCH path = (c:concentration)-[:INCLUDE*]->(p:Courses)
WHERE c.Concentration = "Finance" OR c.Concentration = "Entrepreneurship"
OPTIONAL MATCH prereqPath = (p)<-[:UNLOCKS*]-(pre:Courses)
RETURN path, prereqPath
""".strip()

if "history" not in st.session_state:
    st.session_state.history = [{
        "name": "FLMB Requirements",
        "query": sample_query_flmb_requirements,
        "nodes": 78,
        "relationships": 70,
        "ts": 0.0
    },{
        "name": "Econ and Finance Concentrations",
        "query": sample_query_econ_and_finance,
        "nodes": 86,
        "relationships": 104,
        "ts": 0.0
    }]

def to_jsonable(value):
    """Make values safe to embed in streamlit-agraph (must be JSON-serializable)."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    # Fallback for Neo4j temporal / other custom objects.
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def run_query_graph(query: str):
    """
    Runs a Cypher query and expects it to return a Neo4j Graph object
    via `result.graph()` (i.e. RETURN nodes/relationships as a graph pattern).
    """
    with driver.session() as session:
        result = session.run(query)
        return result.graph()


def run_query_records(query: str):
    """Runs a Cypher query and returns a list of record dicts."""
    with driver.session() as session:
        result = session.run(query)
        return [record.data() for record in result]


def compute_graph_counts(graph):
    # graph.nodes / graph.relationships are iterables.
    try:
        nodes_count = len(graph.nodes)
    except Exception:
        nodes_count = len(list(graph.nodes))

    try:
        rels_count = len(graph.relationships)
    except Exception:
        rels_count = len(list(graph.relationships))
    return nodes_count, rels_count

# --- Streamlit layout ---
tab1, tab2 = st.tabs(["Explore Classes", "Chart my Path"])

# --- TAB 1: Explore Classes (Neo4j Viz version with sidebar) ---
with tab1:
    st.title("Explore Classes Available at Chicago Booth")
    st.caption("Run a Cypher query, then view the interactive graph below.")

    # --- Initialize session state ---
    if "graph" not in st.session_state:
        st.session_state.graph = None
    if "history" not in st.session_state:
        st.session_state.history = []
    if "node_details_by_id" not in st.session_state:
        st.session_state.node_details_by_id = {}

    default_query = """
    MATCH (n)-[r]->(m)
    RETURN n,r,m
    LIMIT 25
    """.strip()

    # --- Sidebar: Cypher Query ---
    st.sidebar.write(
        "To learn more about Cypher queries, refer to the "
        "[Neo4j documentation](https://neo4j.com/product/cypher-graph-query-language/)"
    )
    query = st.sidebar.text_area("Enter Cypher Query", default_query, height=200)

    if st.sidebar.button("Run Query"):
        try:
            graph = run_query_graph(query)
            st.session_state.graph = graph

            # --- Update query history ---
            nodes_count = len(graph.nodes)
            rels_count = len(graph.relationships)
            if not any(h.get("query") == query for h in st.session_state.history):
                st.session_state.history.insert(
                    0,
                    {
                        "query": query.strip(),
                        "nodes": nodes_count,
                        "relationships": rels_count,
                        "ts": time.time(),
                    },
                )
                st.session_state.history = st.session_state.history[:12]

        except Exception as e:
            st.sidebar.error(f"Query failed: {e}")

    # --- Sidebar: Query History ---
    st.sidebar.subheader("Query History")
    if st.session_state.history:
        for i, entry in enumerate(st.session_state.history):
            name = entry.get("name", f"Query #{i+1}")
            past_query = entry.get("query", "")
            nodes_count = entry.get("nodes", 0)
            rels_count = entry.get("relationships", 0)
            
            with st.sidebar.expander(f"{name} (nodes: {nodes_count}, rels: {rels_count})", expanded=False):
                st.code(past_query, language="cypher")
                if st.button("Run again", key=f"history_run_{i}"):
                    try:
                        graph = run_query_graph(past_query)
                        st.session_state.graph = graph
                    except Exception as e:
                        st.sidebar.error(f"Query failed: {e}")
    else:
        st.sidebar.caption("Run a query to populate history.")

    # --- Sidebar: Schema Explorer ---
    st.sidebar.divider()
    st.sidebar.subheader("Schema Explorer")

    def fetch_schema():
        node_types = run_query_records(
            """
            MATCH (n)
            UNWIND labels(n) AS label
            RETURN label, count(*) AS count
            ORDER BY count DESC
            LIMIT 30
            """
        )
        rel_types = run_query_records(
            """
            MATCH ()-[r]->()
            RETURN type(r) AS type, count(*) AS count
            ORDER BY count DESC
            LIMIT 30
            """
        )
        top_label_pairs = run_query_records(
            """
            MATCH (a)-[r]->(b)
            WITH
            CASE WHEN size(labels(a)) > 0 THEN labels(a)[0] ELSE 'None' END AS fromLabel,
            type(r) AS relType,
            CASE WHEN size(labels(b)) > 0 THEN labels(b)[0] ELSE 'None' END AS toLabel
            RETURN fromLabel, relType, toLabel, count(*) AS count
            ORDER BY count DESC
            LIMIT 30
            """
        )
        return {"node_types": node_types, "relationship_types": rel_types, "top_label_pairs": top_label_pairs}

    if st.sidebar.button("Refresh schema"):
        try:
            st.session_state.schema = fetch_schema()
        except Exception as e:
            st.sidebar.error(f"Failed to fetch schema: {e}")

    if "schema" not in st.session_state or st.session_state.schema is None:
        try:
            st.session_state.schema = fetch_schema()
        except Exception:
            st.sidebar.caption("Schema not available yet (check Neo4j connection).")

    node_types = st.session_state.schema.get("node_types", []) if st.session_state.schema else []
    rel_types = st.session_state.schema.get("relationship_types", []) if st.session_state.schema else []
    top_label_pairs = st.session_state.schema.get("top_label_pairs", []) if st.session_state.schema else []

    with st.sidebar.expander("Node types", expanded=True):
        if node_types:
            for row in node_types:
                st.write(f"{row.get('label')} ({row.get('count', 0)})")
        else:
            st.caption("No node types found.")

    with st.sidebar.expander("Relationship types", expanded=False):
        if rel_types:
            for row in rel_types:
                st.write(f"{row.get('type')} ({row.get('count', 0)})")
        else:
            st.caption("No relationship types found.")

    with st.sidebar.expander("Top relationship patterns", expanded=False):
        if top_label_pairs:
            for row in top_label_pairs:
                st.write(
                    f"{row.get('fromLabel')} -[{row.get('relType')}]-> {row.get('toLabel')} ({row.get('count', 0)})"
                )
        else:
            st.caption("No relationship patterns found.")

    # --- Main: Render Neo4j Viz graph as HTML in Streamlit ---
    if st.session_state.graph:
        try:
            VG = from_neo4j(st.session_state.graph)

            VG.color_nodes(
                field="caption",
                colors=[
                    "#FF7F7F",          # pale red
                    "#7FFFD4",          # aquamarine
                    "#FFD700",          # gold
                    "#9370DB"           # medium purple
                ],
                color_space=ColorSpace.DISCRETE
            )
           
            html_obj = VG.render(
                layout="forcedirected",
                width="100%",  # wider than height
                height="800px",  # shorter than width
            )

            # `html_obj` is IPython.display.HTML
            html_content = html_obj.data if hasattr(html_obj, "data") else html_obj
            html_content = html_content.replace(
                "<body>", '<body style="background-color:#000000;">'
            )

            components.html(html_content, height=700, width="100%", scrolling=True)

        except Exception as e:
            st.error(f"Failed to render graph: {e}")
    else:
        st.caption("Run a Cypher query to visualize nodes and relationships.")
    # ---------------------------
# TAB 2 — Chart My Path
# ---------------------------
with tab2:

    st.title("Chart My Path")
    st.caption("Plan the sequence of courses for your Booth journey.")

    st.info("Path planning features coming soon.")

    # Example placeholder UI
    concentrations = st.multiselect(
        "Select your concentrations",
        load_concentrations(),
    )
    
    selected_courses = st.multiselect(
        "Courses you've already taken",
        load_courses(),
    )

    if st.button("Generate Suggested Path"):
        generate_suggested_path(concentrations, selected_courses, driver)