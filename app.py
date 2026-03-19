import os
import json
import time
import streamlit as st
from neo4j import GraphDatabase
from streamlit_agraph import agraph, Node, Edge, Config

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(
        st.secrets["NEO4J_URI"],
        auth=(st.secrets["NEO4J_USERNAME"], st.secrets["NEO4J_PASSWORD"])
    )

driver = get_driver()


# ---------------------------
# Helpers
# ---------------------------

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
st.title("Neo4j Graph Explorer")
st.caption("Run a Cypher query, then click nodes to view their properties.")

# Initialize session state
if "graph" not in st.session_state:
    st.session_state.graph = None
if "history" not in st.session_state:
    st.session_state.history = []
if "selected_node" not in st.session_state:
    st.session_state.selected_node = None
if "schema" not in st.session_state:
    st.session_state.schema = None
if "node_details_by_id" not in st.session_state:
    st.session_state.node_details_by_id = {}

# Sidebar query input
st.sidebar.header("Cypher Query")

default_query = """
MATCH (n)-[r]->(m)
RETURN n,r,m
LIMIT 25
""".strip()
query = st.sidebar.text_area("Enter Cypher Query", default_query, height=200)

# Backward-compat: if history still contains raw strings, convert them.
if st.session_state.history and isinstance(st.session_state.history[0], str):
    st.session_state.history = [
        {"query": q, "nodes": 0, "relationships": 0, "ts": 0.0} for q in st.session_state.history
    ]

if st.sidebar.button("Run Query"):
    try:
        graph = run_query_graph(query)
    except Exception as e:
        st.sidebar.error(f"Query failed: {e}")
    else:
        nodes_count, rels_count = compute_graph_counts(graph)
        st.session_state.graph = graph
        st.session_state.selected_node = None

        is_new = not any(h.get("query") == query for h in st.session_state.history)
        if is_new:
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

# Selected node details (in sidebar, right below the query box)
st.sidebar.divider()
st.sidebar.subheader("Selected Node")
selected = st.session_state.get("selected_node")
if not selected:
    st.sidebar.caption("Click a node in the graph to view its values.")
else:
    selected_id = selected.get("id")
    selected_label = selected.get("label")
    st.sidebar.write(f"ID: `{selected_id}`")
    if selected_label:
        st.sidebar.write(f"Label: `{selected_label}`")

    props = selected.get("properties")
    with st.sidebar.expander("Properties", expanded=True):
        if isinstance(props, dict) and props:
            st.sidebar.json(props)
        else:
            st.sidebar.write("No properties payload returned.")

# Show query history (actual Cypher shown in the sidebar)
st.sidebar.subheader("Query History")
if st.session_state.history:
    for i, entry in enumerate(st.session_state.history):
        past_query = entry.get("query", "")
        nodes_count = entry.get("nodes", 0)
        rels_count = entry.get("relationships", 0)
        with st.sidebar.expander(f"#{i+1} (nodes: {nodes_count}, rels: {rels_count})", expanded=False):
            st.code(past_query, language="cypher")
            if st.button("Run again", key=f"history_run_{i}"):
                try:
                    graph = run_query_graph(past_query)
                except Exception as e:
                    st.sidebar.error(f"Query failed: {e}")
                else:
                    st.session_state.graph = graph
                    st.session_state.selected_node = None
else:
    st.sidebar.caption("Run a query to populate history.")

# ---------------------------
# Schema Explorer
# ---------------------------
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

if st.session_state.schema is None:
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

# ---------------------------
# Main: Graph rendering
# ---------------------------
if st.session_state.graph:
    graph = st.session_state.graph
    nodes = []
    edges = []
    node_ids = set()
    node_details_by_id = {}

    for node in graph.nodes:
        if node.id in node_ids:
            continue
        node_ids.add(node.id)

        props = dict(node)
        safe_props = {k: to_jsonable(v) for k, v in props.items()}

        # Priority-based label
        if "course_name" in props:
            node_label = props["course_name"]
        elif "concentration" in props:
            node_label = props["concentration"]
        elif "foundation" in props:
            node_label = props["foundation"]
        else:
            node_label = list(node.labels)[0] if getattr(node, "labels", None) else "Node"

        node_details_by_id[str(node.id)] = {
            "id": node.id,
            "label": str(node_label),
            "properties": safe_props,
            "labels": list(node.labels) if getattr(node, "labels", None) else [],
        }

        nodes.append(
            Node(
                id=node.id,
                label=str(node_label),
                title=str(safe_props),  # hover tooltip with all properties
                size=25,
                color="lightblue",
                properties=safe_props,  # kept for potential future payloads
                labels=list(node.labels) if getattr(node, "labels", None) else [],
            )
        )

    st.session_state.node_details_by_id = node_details_by_id

    for rel in graph.relationships:
        edges.append(
            Edge(source=rel.start_node.id, target=rel.end_node.id, label=rel.type)
        )

    config = Config(
        width=900,
        height=700,
        directed=True,
        physics=True,
        physics_config={
            "enabled": True,
            "stabilization": {"enabled": True, "iterations": 2000},
            "barnesHut": {
                "gravitationalConstant": -500,
                "centralGravity": 0.0,
                "springLength": 150,
                "springConstant": 0.8,
                "damping": 0.9,
            },
        },
    )

    clicked_node = agraph(nodes=nodes, edges=edges, config=config)
    if clicked_node is None:
        st.session_state.selected_node = None
    elif isinstance(clicked_node, dict):
        # Older/alternate payloads might return a dict.
        node_id = clicked_node.get("id")
        st.session_state.selected_node = st.session_state.node_details_by_id.get(
            str(node_id), clicked_node
        )
    else:
        # streamlit-agraph typically returns the clicked node id (scalar)
        st.session_state.selected_node = st.session_state.node_details_by_id.get(str(clicked_node))
else:
    st.caption("Run a Cypher query to visualize nodes and relationships.")