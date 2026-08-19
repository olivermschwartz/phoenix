import os
import json
import time
import pandas as pd
import streamlit as st
from neo4j import GraphDatabase
# from path_gen import generate_suggested_path
import tempfile
import streamlit.components.v1 as components
from neo4j_viz.neo4j import from_neo4j
from neo4j_viz.colors import ColorSpace
from palettable.wesanderson import Moonrise1_5
import ortools.sat.python.cp_model as cp

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

NODE_TYPE_COLORS = {
    "Course": "#FF7F7F",
    "Strategic Pick": "#FF3B30",
    "Not Offered In Selected Terms": "#6F7378",
    "Concentration": "#7FFFD4",
    "FLMB Requirement": "#FFD700",
    "Foundation": "#9370DB",
    "Suggested Path": "#90EE90",
    "Other": "#B8B8B8",
}

DEFAULT_VISUAL_SETTINGS = {
    "avg_recommendation": 4,
    "low_workload": 2,
    "selected_terms": [],
    "lookback_years": None,
}

TERM_OPTIONS = ["Winter", "Spring", "Summer", "Autumn"]

CONCENTRATION_COURSE_REQUIREMENTS = {
    "Accounting": 4,
    "Applied Artificial Intelligence": 3,
    "Behavioral Science": 4,
    "Business Analytics": 5,
    "Business Society and Sustainability": 4,
    "Econometrics and Statistics": 3,
    "Economics": 4,
    "Entrepreneurship": 3,
    "Finance": 4,
    "Analytic Finance": 6,
    "Healthcare": 4,
    "International Business": 3,
    "Marketing Management": 4,
    "Operations Management": 3,
    "Strategic Management": 4,
}

@st.cache_data
def load_concentrations():
    path = os.path.join(BASE_DIR, "../data/concentrations.csv")
    df = pd.read_csv(path)
    return df["Concentration"].dropna().tolist()

@st.cache_data
def load_courses():
    path = os.path.join(BASE_DIR, "../data/courses.csv")
    df = pd.read_csv(path)
    return df["course_name"].dropna().tolist()

@st.cache_data
def load_flmb_requirement_types():
    path = os.path.join(BASE_DIR, "../data/flmb_entities.csv")
    df = pd.read_csv(path)
    return df["flmb_sub_type"].dropna().tolist()

@st.cache_data
def load_foundations():
    path = os.path.join(BASE_DIR, "../data/foundations_entities.csv")
    df = pd.read_csv(path)
    return df["foundation"].dropna().tolist()

@st.cache_data
def load_degree_requirement_text():
    path = os.path.join(BASE_DIR, "../data/degree_requirements")
    with open(path, "r", encoding="utf-8") as file:
        return file.read()

@st.cache_data
def load_foundation_requirements_map():
    path = os.path.join(BASE_DIR, "../data/foundations_map.csv")
    df = pd.read_csv(path)
    df["course_number"] = df["course_number"].astype(str)
    return df

@st.cache_data
def load_flmb_requirements_map():
    path = os.path.join(BASE_DIR, "../data/flmb_edges.csv")
    df = pd.read_csv(path)
    df["course_number"] = df["course_number"].astype(str)
    return df

@st.cache_data
def load_concentration_requirements_map():
    path = os.path.join(BASE_DIR, "../data/concentration_map.csv")
    df = pd.read_csv(path)
    df["Class Number"] = df["Class Number"].astype(str)
    return df

sample_query_flmb_requirements = """
MATCH (n:Course)-[r:HAS_FLMB_SUB_TYPE]->(b:FlmbSubType)
RETURN n, r, b
""".strip()

sample_query_all = """
MATCH (n)-[r]->(m)
RETURN n,r,m
LIMIT 25
""".strip()

sample_query_entr_and_finance = """
MATCH path = (p:Course)-[:BELONGS_TO*]->(c:Concentration)
WHERE c.concentration = "Finance" OR c.concentration = "Entrepreneurship"
OPTIONAL MATCH prereqPath = (p)-[:REQUIRES*]->(pre:Course)
RETURN path, prereqPath
""".strip()

if "history" not in st.session_state:
    st.session_state.history = [{
        "name": "Entrepreneurship and Finance Concentrations",
        "query": sample_query_entr_and_finance,
        "nodes": 86,
        "relationships": 104,
        "ts": 0.0
    },{
        "name": "FLMB Requirements",
        "query": sample_query_flmb_requirements,
        "nodes": 78,
        "relationships": 70,
        "ts": 0.0
    }, {
        "name": "Get All", 
        "query": sample_query_all, 
        "nodes": 30, 
        "relationships": 25, 
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


def node_to_properties(node):
    try:
        return dict(node)
    except Exception:
        return getattr(node, "properties", {})


def node_to_labels(node):
    labels = getattr(node, "labels", None)
    if labels is not None:
        return list(labels)
    properties = node_to_properties(node)
    labels = properties.get("labels", [])
    if isinstance(labels, list):
        return labels
    return [labels] if labels else []


def visible_courses_from_graph(graph):
    if not graph:
        return []

    courses_by_number = {}
    for node in list(graph.nodes):
        labels = node_to_labels(node)
        properties = node_to_properties(node)
        is_temp_suggested_node = "course_name" in properties
        if "Course" not in labels and not is_temp_suggested_node:
            continue

        if is_temp_suggested_node:
            course_number = properties.get("course_number")
            course_name = properties.get("course_name")
        else:
            course_number = properties.get("courseNumber")
            course_name = properties.get("courseName")
        if course_number is None or not course_name:
            continue

        course_number = str(course_number)
        courses_by_number[course_number] = {
            "course_number": course_number,
            "course_name": course_name,
            "label": f"{course_number} - {course_name}",
        }

    return sorted(courses_by_number.values(), key=lambda course: course["label"])


def is_course_node(node):
    labels = node.properties.get("labels", [])
    if not isinstance(labels, list):
        labels = [labels]
    return "Course" in labels


def get_course_name(node):
    return node.properties.get("courseName")


def get_node_type(node):
    labels = node.properties.get("labels", [])
    if not isinstance(labels, list):
        labels = [labels]

    if "Course" in labels:
        return "Course"
    if "Concentration" in labels:
        return "Concentration"
    if any(str(label).startswith("SuggestedCourse_") for label in labels):
        return "Suggested Path"
    if "flmbSubType" in node.properties:
        return "FLMB Requirement"
    if "foundation" in node.properties:
        return "Foundation"
    return "Other"


def get_numeric_property(node, property_name):
    value = node.properties.get(property_name)
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_terms_offered(terms_offered):
    if not isinstance(terms_offered, str):
        return []

    terms = []
    for entry in terms_offered.split(","):
        parts = entry.strip().split()
        if len(parts) != 2:
            continue
        term, year = parts
        try:
            terms.append({"term": term.title(), "year": int(year)})
        except ValueError:
            continue
    return terms


def course_matches_term_filter(node, selected_terms, lookback_years):
    if not selected_terms:
        return True

    current_year = pd.Timestamp.today().year
    min_year = current_year - lookback_years if lookback_years is not None else None
    selected_terms = set(selected_terms)

    for offering in parse_terms_offered(node.properties.get("termsOffered")):
        if offering["term"] not in selected_terms:
            continue
        if min_year is not None and offering["year"] < min_year:
            continue
        return True
    return False


def normalize_values(nodes, property_name, higher_is_better=True):
    values_by_id = {
        node.id: value
        for node in nodes
        if (value := get_numeric_property(node, property_name)) is not None
    }
    if not values_by_id:
        return {}

    min_value = min(values_by_id.values())
    max_value = max(values_by_id.values())
    if min_value == max_value:
        return {node_id: 0.5 for node_id in values_by_id}

    normalized = {}
    for node_id, value in values_by_id.items():
        score = (value - min_value) / (max_value - min_value)
        normalized[node_id] = score if higher_is_better else 1 - score
    return normalized


def apply_course_node_sizes(nodes, visual_settings):
    course_nodes = [node for node in nodes if is_course_node(node)]
    if not course_nodes:
        return

    recommendation_weight = visual_settings.get("avg_recommendation", 0)
    workload_weight = visual_settings.get("low_workload", 0)
    total_weight = recommendation_weight + workload_weight
    recommendation_scores = normalize_values(course_nodes, "avgRecommendation", higher_is_better=True)
    workload_scores = normalize_values(course_nodes, "avgHoursOfWork", higher_is_better=False)

    for node in nodes:
        if not is_course_node(node):
            continue

        if total_weight <= 0:
            course_score = 0.5
        else:
            weighted_score = 0
            weighted_score += recommendation_weight * recommendation_scores.get(node.id, 0.5)
            weighted_score += workload_weight * workload_scores.get(node.id, 0.5)
            course_score = weighted_score / total_weight

        node.properties["priority_score"] = round(course_score, 3)
        node.size = 18 + (course_score * 34)


def fetch_selected_requirement_counts(concentrations, flmb_types, foundations):
    requirements_by_course = {}

    def add_requirement(course_name, requirement):
        if course_name:
            requirements_by_course.setdefault(course_name, set()).add(requirement)

    with driver.session() as session:
        if concentrations:
            result = session.run(
                """
                MATCH (course:Course)-[:BELONGS_TO*]->(c:Concentration)
                WHERE c.concentration IN $concentrations
                RETURN course.courseName AS course_name, collect(DISTINCT c.concentration) AS requirements
                """,
                {"concentrations": concentrations},
            )
            for record in result:
                for requirement in record["requirements"]:
                    add_requirement(record["course_name"], f"Concentration: {requirement}")

        if flmb_types:
            result = session.run(
                """
                MATCH (course:Course)-[:HAS_FLMB_SUB_TYPE]->(requirement:FlmbSubType)
                WHERE requirement.flmbSubType IN $flmb_types
                RETURN course.courseName AS course_name, collect(DISTINCT requirement.flmbSubType) AS requirements
                """,
                {"flmb_types": flmb_types},
            )
            for record in result:
                for requirement in record["requirements"]:
                    add_requirement(record["course_name"], f"FLMB: {requirement}")

        if foundations:
            result = session.run(
                """
                MATCH (course:Course)-[:SATISFIES_FOUNDATION]->(foundation:Foundation)
                WHERE foundation.foundation IN $foundations
                RETURN course.courseName AS course_name, collect(DISTINCT foundation.foundation) AS requirements
                """,
                {"foundations": foundations},
            )
            for record in result:
                for requirement in record["requirements"]:
                    add_requirement(record["course_name"], f"Foundation: {requirement}")

    return {
        course_name: {
            "count": len(requirements),
            "requirements": sorted(requirements),
        }
        for course_name, requirements in requirements_by_course.items()
    }


def summarize_degree_progress(selected_course_numbers):
    selected_course_numbers = {str(course_number) for course_number in selected_course_numbers}
    foundation_map = load_foundation_requirements_map()
    flmb_map = load_flmb_requirements_map()

    selected_foundations = sorted(
        foundation_map[foundation_map["course_number"].isin(selected_course_numbers)]["foundation"].dropna().unique()
    )
    selected_flmb_categories = sorted(
        flmb_map[flmb_map["course_number"].isin(selected_course_numbers)]["flmb_sub_type"].dropna().unique()
    )

    return {
        "foundations": selected_foundations,
        "flmb_categories": selected_flmb_categories,
        "electives_count": len(selected_course_numbers),
        "foundation_total": len(load_foundations()),
        "flmb_required": 7,
        "electives_required": 10,
    }


def course_requirement_tags(course_number):
    course_number = str(course_number)
    foundation_map = load_foundation_requirements_map()
    flmb_map = load_flmb_requirements_map()
    concentration_map = load_concentration_requirements_map()

    tags = []
    foundations = foundation_map[foundation_map["course_number"] == course_number]["foundation"].dropna().unique()
    flmb_categories = flmb_map[flmb_map["course_number"] == course_number]["flmb_sub_type"].dropna().unique()
    concentrations = concentration_map[
        concentration_map["Class Number"] == course_number
    ]["Concentration"].dropna().unique()
    tags.extend(f"Foundation: {foundation}" for foundation in sorted(foundations))
    tags.extend(f"FLMB: {category}" for category in sorted(flmb_categories))
    tags.extend(f"Concentration: {concentration}" for concentration in sorted(concentrations))
    tags.append("Elective")
    return tags


def summarize_concentration_progress(selected_course_numbers):
    selected_course_numbers = {str(course_number) for course_number in selected_course_numbers}
    concentration_map = load_concentration_requirements_map()
    rows = []

    for concentration, required_count in CONCENTRATION_COURSE_REQUIREMENTS.items():
        eligible_courses = set(
            concentration_map[
                concentration_map["Concentration"] == concentration
            ]["Class Number"]
        )
        matching_courses = selected_course_numbers & eligible_courses
        rows.append(
            {
                "Concentration": concentration,
                "Planned": len(matching_courses),
                "Required": required_count,
                "Progress": min(len(matching_courses) / required_count, 1),
                "Complete": len(matching_courses) >= required_count,
            }
        )

    return sorted(rows, key=lambda row: (not row["Complete"], -row["Progress"], row["Concentration"]))


def visible_courses_for_unmet_requirements(visible_courses, selected_course_numbers, progress):
    selected_course_numbers = {str(course_number) for course_number in selected_course_numbers}
    visible_course_numbers = {course["course_number"] for course in visible_courses} - selected_course_numbers
    foundation_map = load_foundation_requirements_map()
    flmb_map = load_flmb_requirements_map()

    unmet_foundations = set(load_foundations()) - set(progress["foundations"])
    unmet_flmb_slots_remaining = max(progress["flmb_required"] - len(progress["flmb_categories"]), 0)
    unmet_flmb_categories = set(load_flmb_requirement_types()) - set(progress["flmb_categories"])

    suggestions = {}
    for foundation in sorted(unmet_foundations):
        course_numbers = set(
            foundation_map[
                (foundation_map["foundation"] == foundation)
                & (foundation_map["course_number"].isin(visible_course_numbers))
            ]["course_number"]
        )
        if course_numbers:
            suggestions[f"Foundation: {foundation}"] = course_numbers

    if unmet_flmb_slots_remaining > 0:
        for category in sorted(unmet_flmb_categories):
            course_numbers = set(
                flmb_map[
                    (flmb_map["flmb_sub_type"] == category)
                    & (flmb_map["course_number"].isin(visible_course_numbers))
                ]["course_number"]
            )
            if course_numbers:
                suggestions[f"FLMB: {category}"] = course_numbers

    if progress["electives_count"] < progress["electives_required"]:
        suggestions["Electives"] = visible_course_numbers

    return suggestions


def render_degree_progress_panel():
    visible_courses = visible_courses_from_graph(st.session_state.graph)
    if "selected_degree_courses" not in st.session_state:
        st.session_state.selected_degree_courses = []

    st.subheader("Degree Requirements Planner")
    st.caption("Tag visible classes to see how they can satisfy Booth graduation requirements.")

    if not visible_courses:
        st.info("Run a graph query with course nodes to tag classes toward degree requirements.")
        return

    course_labels_by_number = {
        course["course_number"]: course["label"] for course in visible_courses
    }
    selected_course_numbers = [
        course_number
        for course_number in st.session_state.selected_degree_courses
        if course_number in course_labels_by_number
    ]
    st.session_state.selected_degree_courses = selected_course_numbers

    progress = summarize_degree_progress(selected_course_numbers)
    foundation_count = len(progress["foundations"])
    flmb_count = min(len(progress["flmb_categories"]), progress["flmb_required"])
    elective_count = min(progress["electives_count"], progress["electives_required"])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Foundations", f"{foundation_count}/{progress['foundation_total']}")
        st.progress(foundation_count / progress["foundation_total"] if progress["foundation_total"] else 0)
        st.caption(", ".join(progress["foundations"]) if progress["foundations"] else "No foundations tagged yet.")
    with col2:
        st.metric("FLMB", f"{flmb_count}/{progress['flmb_required']}")
        st.progress(flmb_count / progress["flmb_required"])
        st.caption(", ".join(progress["flmb_categories"]) if progress["flmb_categories"] else "No FLMB categories tagged yet.")
    with col3:
        st.metric("Electives", f"{elective_count}/{progress['electives_required']}")
        st.progress(elective_count / progress["electives_required"])
        st.caption("Any tagged class can count toward the elective pool.")

    st.markdown("**Tagged Classes**")
    if selected_course_numbers:
        tagged_rows = []
        for course_number in selected_course_numbers:
            tagged_rows.append(
                {
                    "Course": course_labels_by_number.get(course_number, course_number),
                    "Satisfies": ", ".join(course_requirement_tags(course_number)),
                }
            )
        st.dataframe(pd.DataFrame(tagged_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No classes tagged yet. Select a class above the graph and click Add to Plan.")

    st.markdown("**Concentration Progress**")
    concentration_progress = summarize_concentration_progress(selected_course_numbers)
    completed_concentrations = [
        row["Concentration"] for row in concentration_progress if row["Complete"]
    ]
    if completed_concentrations:
        st.success(f"Completed: {', '.join(completed_concentrations)}")
    else:
        st.caption("No concentrations completed yet.")

    concentration_rows = []
    for row in concentration_progress:
        if row["Planned"] == 0 and not row["Complete"]:
            continue
        concentration_rows.append(
            {
                "Concentration": row["Concentration"],
                "Progress": f"{row['Planned']}/{row['Required']}",
                "Status": "Complete" if row["Complete"] else "In progress",
            }
        )

    if concentration_rows:
        st.dataframe(pd.DataFrame(concentration_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Add concentration-eligible classes to see concentration progress.")
    st.caption("Concentration progress uses eligible-course counts from the concentration map; detailed subcategory rules are not audited yet.")

def render_add_to_plan_controls():
    visible_courses = visible_courses_from_graph(st.session_state.graph)
    if "selected_degree_courses" not in st.session_state:
        st.session_state.selected_degree_courses = []

    if not visible_courses:
        return

    course_labels_by_number = {
        course["course_number"]: course["label"] for course in visible_courses
    }
    selected_course = st.selectbox(
        "Course to add",
        options=[None] + list(course_labels_by_number.keys()),
        format_func=lambda course_number: (
            "Select a class to add to the plan below"
            if course_number is None
            else course_labels_by_number[course_number]
        ),
        label_visibility="collapsed",
        key="course_to_add_to_plan",
    )

    if st.button("Add to Plan", use_container_width=True):
        if selected_course and selected_course not in st.session_state.selected_degree_courses:
            st.session_state.selected_degree_courses.append(selected_course)
            st.rerun()


def open_neo4j_visual_sidepanel(html_content):
    closed_panel_initializer = "[_,S]=vr.useState(!1),[E,O]=vr.useState(300)"
    open_panel_initializer = "[_,S]=vr.useState(!0),[E,O]=vr.useState(300)"
    return html_content.replace(closed_panel_initializer, open_panel_initializer, 1)


def style_graph_html(html_content):
    html_content = open_neo4j_visual_sidepanel(html_content)
    return html_content.replace(
        "<body>", '<body style="background-color:#000000;">'
    )


def clamp_visual_settings(settings):
    selected_terms = [
        term for term in settings.get("selected_terms", []) if term in TERM_OPTIONS
    ]
    lookback_years = settings.get("lookback_years")
    if lookback_years is not None:
        try:
            lookback_years = min(max(int(lookback_years), 1), pd.Timestamp.today().year - 2020)
        except (TypeError, ValueError):
            lookback_years = None

    return {
        "avg_recommendation": min(max(int(settings.get("avg_recommendation", 4)), 0), 5),
        "low_workload": min(max(int(settings.get("low_workload", 2)), 0), 5),
        "selected_terms": selected_terms,
        "lookback_years": lookback_years,
    }


def render_node_legend():
    legend_items = "".join(
        f"""
        <div class="legend-item">
            <span class="legend-swatch" style="background:{color};"></span>
            <span>{label}</span>
        </div>
        """
        for label, color in NODE_TYPE_COLORS.items()
    )
    st.markdown(
        f"""
        <style>
            .node-legend {{
                display: flex;
                flex-wrap: wrap;
                gap: 0.45rem 1rem;
                align-items: center;
                margin: 0.5rem 0 0.75rem;
                font-size: 0.9rem;
            }}
            .legend-item {{
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                white-space: nowrap;
            }}
            .legend-swatch {{
                display: inline-block;
                width: 0.85rem;
                height: 0.85rem;
                border-radius: 999px;
                border: 1px solid rgba(255, 255, 255, 0.45);
            }}
        </style>
        <div class="node-legend">{legend_items}</div>
        """,
        unsafe_allow_html=True,
    )


def cypher_list(values):
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"


def build_guided_query(concentrations, flmb_types, foundations, include_prerequisites=True):
    query_branches = []

    if concentrations:
        branch = f"""
        MATCH path = (course:Course)-[:BELONGS_TO*]->(c:Concentration)
        WHERE c.concentration IN {cypher_list(concentrations)}
        """
        if include_prerequisites:
            branch += """
        OPTIONAL MATCH prereqPath = (course)-[:REQUIRES*]->(pre:Course)
        """
        else:
            branch += """
        WITH path, null AS prereqPath
        """
        branch += """
        RETURN path, prereqPath, null AS requirement, null AS foundation, null AS rel, null AS course
        """
        query_branches.append(branch.strip())

    if flmb_types:
        branch = f"""
        MATCH (course:Course)-[rel:HAS_FLMB_SUB_TYPE]->(requirement:FlmbSubType)
        WHERE requirement.flmbSubType IN {cypher_list(flmb_types)}
        """
        if include_prerequisites:
            branch += """
        OPTIONAL MATCH prereqPath = (course)-[:REQUIRES*]->(pre:Course)
        """
        else:
            branch += """
        WITH requirement, rel, course, null AS prereqPath
        """
        branch += """
        RETURN null AS path, prereqPath, requirement, null AS foundation, rel, course
        """
        query_branches.append(branch.strip())

    if foundations:
        branch = f"""
        MATCH (course:Course)-[rel:SATISFIES_FOUNDATION]->(foundation:Foundation)
        WHERE foundation.foundation IN {cypher_list(foundations)}
        """
        if include_prerequisites:
            branch += """
        OPTIONAL MATCH prereqPath = (course)-[:REQUIRES*]->(pre:Course)
        """
        else:
            branch += """
        WITH foundation, rel, course, null AS prereqPath
        """
        branch += """
        RETURN null AS path, prereqPath, null AS requirement, foundation, rel, course
        """
        query_branches.append(branch.strip())

    if not query_branches:
        return sample_query_entr_and_finance

    return "\nUNION\n".join(query_branches)


def add_query_history(name, query, graph, visual_settings=None, requirement_counts=None):
    nodes_count, rels_count = compute_graph_counts(graph)
    query = query.strip()
    st.session_state.history = [
        entry for entry in st.session_state.history if entry.get("query") != query
    ]
    st.session_state.history.insert(
        0,
        {
            "name": name,
            "query": query,
            "nodes": nodes_count,
            "relationships": rels_count,
            "ts": time.time(),
            "visual_settings": visual_settings or DEFAULT_VISUAL_SETTINGS.copy(),
            "requirement_counts": requirement_counts or {},
        },
    )
    st.session_state.history = st.session_state.history[:12]


def render_graph_html(graph, height="800px", visual_settings=None, requirement_counts=None):
    VG = from_neo4j(graph)
    visual_settings = clamp_visual_settings(visual_settings or DEFAULT_VISUAL_SETTINGS.copy())
    requirement_counts = requirement_counts or {}

    for node in VG.nodes:
        course_name = get_course_name(node)
        is_multi_requirement_course = (
            is_course_node(node)
            and course_name in requirement_counts
            and requirement_counts[course_name].get("count", 0) > 1
        )
        node.properties["legend_type"] = get_node_type(node)
        if is_course_node(node) and not course_matches_term_filter(
            node,
            visual_settings.get("selected_terms", []),
            visual_settings.get("lookback_years"),
        ):
            node.properties["legend_type"] = "Not Offered In Selected Terms"
        elif is_multi_requirement_course:
            node.properties["legend_type"] = "Strategic Pick"
            node.properties["selected_requirement_count"] = requirement_counts[course_name]["count"]
            node.properties["selected_requirements"] = requirement_counts[course_name]["requirements"]

    VG.color_nodes(
        property="legend_type",
        colors=NODE_TYPE_COLORS,
        color_space=ColorSpace.DISCRETE,
    )
    apply_course_node_sizes(VG.nodes, visual_settings)

    html_obj = VG.render(
        layout="forcedirected",
        width="100%",
        height=height,
    )
    html_content = html_obj.data if hasattr(html_obj, "data") else html_obj
    return style_graph_html(html_content)


def execute_graph_query(query, name="Query", visual_settings=None, requirement_counts=None):
    graph = run_query_graph(query)
    st.session_state.graph = graph
    st.session_state.visual_settings = clamp_visual_settings(visual_settings or DEFAULT_VISUAL_SETTINGS.copy())
    st.session_state.requirement_counts = requirement_counts or {}
    st.session_state.graph_html = render_graph_html(
        graph,
        visual_settings=st.session_state.visual_settings,
        requirement_counts=st.session_state.requirement_counts,
    )
    add_query_history(
        name,
        query,
        graph,
        visual_settings=st.session_state.visual_settings,
        requirement_counts=st.session_state.requirement_counts,
    )
    return graph

if "welcomed" not in st.session_state:
    st.session_state.welcomed = False

if not st.session_state.welcomed:
    st.markdown("""
        <style>
        /* hide all default streamlit chrome except our content */
        [data-testid="stSidebar"], [data-testid="stHeader"] { display: none; }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div style="
            background-color: #3d0c0c;
            border: 1px solid #a83232;
            border-radius: 8px;
            padding: 2rem 2.5rem;
            max-width: 900px;
            margin: 8rem auto;
            color: #f5a5a5;
            font-family: monospace;
        ">
            <p><strong>Welcome to Phoenix Planner 🎓</strong></p>
            <p>This tool lets you explore Chicago Booth's course catalog as an interactive graph.</p>
            <p>
                • Nodes represent entities such as courses, concentrations, and requirements<br>
                • Edges represent relationships such as prerequisites or concentration requirements<br>
                • Use the sidebar to run Cypher queries or browse the schema
            </p>
            <p>The initial graph depicts classes that make up the finance and entrepreneurship concentrations, as well as any prerequisites to those classes.</p>
            <p>Stay tuned for features to help you plan your course...</p>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button("Let's explore →", use_container_width=True):
            st.session_state.welcomed = True
            st.rerun()

else:

    # --- Streamlit layout ---
    tab1, tab2 = st.tabs(["Explore Classes", "Chart my Path"])

    # --- TAB 1: Explore Classes (Neo4j Viz version with sidebar) ---
    with tab1:
        st.title("Explore Classes Available at Chicago Booth")
        with st.expander("How to use this page", expanded=True):
            st.markdown(
                """
                1. Use **Course Filters** in the sidebar to choose concentrations, requirements, or foundations.
                2. Click **Show Relationships** to update the class map.
                3. Use **Course Preferences** to make recommended, lower-workload, or recently offered classes stand out.
                4. Choose a class above the map and click **Add to Plan** to track degree and concentration progress below.

                Bigger circles are stronger matches for your preferences. Grey classes do not match the selected term availability.
                """
            )

        # --- Initialize session state ---
        if "graph" not in st.session_state:
            try:
                st.session_state.graph = run_query_graph(sample_query_entr_and_finance)
                st.session_state.visual_settings = DEFAULT_VISUAL_SETTINGS.copy()
                st.session_state.requirement_counts = fetch_selected_requirement_counts(
                    ["Entrepreneurship", "Finance"],
                    [],
                    [],
                )
                st.session_state.graph_html = render_graph_html(
                    st.session_state.graph,
                    visual_settings=st.session_state.visual_settings,
                    requirement_counts=st.session_state.requirement_counts,
                )
            except Exception:
                st.session_state.graph = None
                st.session_state.graph_html = None
                st.session_state.visual_settings = DEFAULT_VISUAL_SETTINGS.copy()
                st.session_state.requirement_counts = {}
        if "history" not in st.session_state:
            st.session_state.history = []
        if "node_details_by_id" not in st.session_state:
            st.session_state.node_details_by_id = {}
        if "visual_settings" not in st.session_state:
            st.session_state.visual_settings = DEFAULT_VISUAL_SETTINGS.copy()
        st.session_state.visual_settings = clamp_visual_settings(st.session_state.visual_settings)
        if "requirement_counts" not in st.session_state:
            st.session_state.requirement_counts = {}

        default_query = sample_query_entr_and_finance

        # --- Sidebar: Query Controls ---
        st.sidebar.header("Course Filters")

        concentration_options = load_concentrations()
        default_concentrations = [
            value for value in ["Entrepreneurship", "Finance"] if value in concentration_options
        ]
        selected_concentrations = st.sidebar.multiselect(
            "Concentrations",
            concentration_options,
            default=default_concentrations,
        )
        selected_flmb_types = st.sidebar.multiselect(
            "FLMB requirement types",
            load_flmb_requirement_types(),
        )
        selected_foundations = st.sidebar.multiselect(
            "Foundations",
            load_foundations(),
        )
        include_prerequisites = st.sidebar.checkbox(
            "Include prerequisite chains",
            value=True,
        )

        generated_query = build_guided_query(
            selected_concentrations,
            selected_flmb_types,
            selected_foundations,
            include_prerequisites,
        )
        builder_signature = (
            tuple(selected_concentrations),
            tuple(selected_flmb_types),
            tuple(selected_foundations),
            include_prerequisites,
        )
        if st.session_state.get("query_builder_signature") != builder_signature:
            st.session_state.query_builder_signature = builder_signature
            st.session_state.query_text = generated_query

        with st.sidebar.form("graph_query_form"):
            with st.expander("Cypher Query", expanded=False):
                query = st.text_area(
                    "Edit generated Cypher",
                    key="query_text",
                    height=260,
                    label_visibility="collapsed",
                )
            run_query = st.form_submit_button("Show Relationships", use_container_width=True)

        st.sidebar.subheader("Course Preferences")
        recommendation_weight = st.sidebar.slider(
            "Average recommendation",
            min_value=0,
            max_value=5,
            value=st.session_state.visual_settings.get("avg_recommendation", 4),
            step=1,
        )
        workload_weight = st.sidebar.slider(
            "Low hours outside class",
            min_value=0,
            max_value=5,
            value=st.session_state.visual_settings.get("low_workload", 2),
            step=1,
        )
        selected_terms = st.sidebar.multiselect(
            "Terms offered",
            TERM_OPTIONS,
            default=st.session_state.visual_settings.get("selected_terms", []),
        )
        max_lookback_years = pd.Timestamp.today().year - 2020
        lookback_options = [None] + list(range(1, max_lookback_years + 1))
        lookback_labels = {
            None: "Any year",
            **{
                years: f"Past {years} year" if years == 1 else f"Past {years} years"
                for years in range(1, max_lookback_years + 1)
            },
        }
        current_lookback_years = st.session_state.visual_settings.get("lookback_years")
        if current_lookback_years not in lookback_options:
            current_lookback_years = None
        lookback_years = st.sidebar.selectbox(
            "Lookback",
            lookback_options,
            index=lookback_options.index(current_lookback_years),
            format_func=lambda value: lookback_labels[value],
        )
        current_visual_settings = {
            "avg_recommendation": recommendation_weight,
            "low_workload": workload_weight,
            "selected_terms": selected_terms,
            "lookback_years": lookback_years,
        }
        if st.session_state.visual_settings != current_visual_settings:
            st.session_state.visual_settings = current_visual_settings
            st.session_state.graph_html = None

        if run_query:
            if not query.strip():
                st.sidebar.warning("Enter a Cypher query to run.")
            else:
                try:
                    selected_groups = []
                    if selected_concentrations:
                        selected_groups.append(f"Concentrations: {', '.join(selected_concentrations)}")
                    if selected_flmb_types:
                        selected_groups.append(f"FLMB: {', '.join(selected_flmb_types)}")
                    if selected_foundations:
                        selected_groups.append(f"Foundations: {', '.join(selected_foundations)}")
                    query_name = " | ".join(selected_groups) if selected_groups else "Custom Cypher Query"
                    requirement_counts = fetch_selected_requirement_counts(
                        selected_concentrations,
                        selected_flmb_types,
                        selected_foundations,
                    )
                    execute_graph_query(
                        query,
                        query_name,
                        visual_settings=current_visual_settings,
                        requirement_counts=requirement_counts,
                    )
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
                            execute_graph_query(
                                past_query,
                                name,
                                visual_settings=current_visual_settings,
                                requirement_counts=entry.get("requirement_counts", {}),
                            )
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
                if not st.session_state.get("graph_html"):
                    st.session_state.graph_html = render_graph_html(
                        st.session_state.graph,
                        visual_settings=st.session_state.visual_settings,
                        requirement_counts=st.session_state.requirement_counts,
                    )
                render_node_legend()
                _, add_to_plan_col = st.columns([3, 2])
                with add_to_plan_col:
                    render_add_to_plan_controls()
                st.session_state.graph_html = style_graph_html(st.session_state.graph_html)
                components.html(st.session_state.graph_html, height=700, width="100%", scrolling=True)
                render_degree_progress_panel()

            except Exception as e:
                st.error(f"Failed to render graph: {e}")
        else:
            st.caption("")

        # ---------------------------
    # ---------------------------
    # TAB 2 — Chart My Path
    # ---------------------------
    with tab2:

        st.title("Chart My Path")
        st.caption("Plan the sequence of courses for your Booth journey.")

        # --- Sidebar / UI Inputs ---
        concentrations = st.multiselect(
            "Select your concentrations",
            load_concentrations(),  # loads from ../data/concentrations.csv
        )

        selected_courses = st.multiselect(
            "Courses you've already taken",
            load_courses(),
        )

        n_future_courses = st.number_input(
            "Max number of future courses to plan",
            min_value=1,
            max_value=20,
            value=10,
            step=1,
        )

        if st.button("Generate Suggested Path"):

            if not concentrations:
                st.warning("Please select at least one concentration.")
            else:

                import pandas as pd
                import uuid

                def generate_suggested_path(concentrations, taken_courses, driver, max_courses=10):
                    """
                    Builds a suggested sequence of courses in Neo4j with all course properties.
                    Uses temporary nodes for visualization.
                    """
                    temp_label = f"SuggestedCourse_{uuid.uuid4().hex[:6]}"

                    # --- Load CSVs ---
                    courses_df = pd.read_csv(os.path.join(BASE_DIR, "../data/courses.csv"))
                    predictions_df = pd.read_csv(os.path.join(BASE_DIR, "../pred/class_term_pred.csv"))

                    # --- Query Neo4j for candidate courses ---
                    # Matches courses under selected concentrations
                    conc_query = """
                    MATCH (course:Course)-[:BELONGS_TO*]->(c:Concentration)
                    WHERE c.concentration IN $concentrations
                    RETURN DISTINCT course
                    """
                    with driver.session() as session:
                        result = session.run(conc_query, {"concentrations": concentrations})
                        candidate_courses = [record["course"]["courseName"] for record in result]

                    # Exclude courses already taken
                    candidate_courses = [c for c in candidate_courses if c not in taken_courses]

                    if not candidate_courses:
                        st.info("No remaining courses to plan for the selected concentrations.")
                        return None

                    # Limit to max_courses
                    candidate_courses = candidate_courses[:max_courses]

                    # --- Create temporary nodes in Neo4j preserving all properties ---
                    with driver.session() as session:
                        for seq, course_name in enumerate(candidate_courses):
                            # Get all course properties from CSV
                            course_props = courses_df[courses_df["course_name"] == course_name].iloc[0].dropna().to_dict()
                            course_props["seq"] = seq  # add sequence property
                            prop_str = ", ".join(f"{k}: ${k}" for k in course_props.keys())
                            session.run(f"CREATE (n:{temp_label} {{{prop_str}}})", course_props)

                        # Create NEXT relationships for ordering
                        for i in range(len(candidate_courses) - 1):
                            session.run(
                                f"""
                                MATCH (a:{temp_label} {{seq: $i}}),
                                    (b:{temp_label} {{seq: $j}})
                                CREATE (a)-[:NEXT]->(b)
                                """,
                                {"i": i, "j": i + 1},
                            )

                    # --- Query temporary path graph ---
                    path_query = f"""
                    MATCH (n:{temp_label})-[r:NEXT*]->(m:{temp_label})
                    RETURN n,r,m
                    """
                    with driver.session() as session:
                        result = session.run(path_query)
                        graph = result.graph()

                    # --- Cleanup temporary nodes ---
                    cleanup_query = f"MATCH (n:{temp_label}) DETACH DELETE n"
                    with driver.session() as session:
                        session.run(cleanup_query)

                    return graph

                # --- Generate and render ---
                try:
                    graph = generate_suggested_path(
                        concentrations, selected_courses, driver, max_courses=n_future_courses
                    )

                    if graph and graph.nodes:
                        html_content = render_graph_html(graph, height="700px")
                        render_node_legend()
                        components.html(html_content, height=700, width="100%", scrolling=True)
                    else:
                        st.info("No suggested path could be generated.")

                except Exception as e:
                    st.error(f"Failed to generate suggested path: {e}")
