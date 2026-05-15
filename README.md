# Phoenix Planner

Phoenix Planner is a Streamlit app for exploring Chicago Booth courses, concentrations, prerequisites, and requirements through a Neo4j graph database. The app visualizes graph query results, exposes useful schema summaries, and includes an early course path planning workflow.

## What the App Does

- Displays Chicago Booth course data as an interactive graph.
- Connects to a Neo4j database using Streamlit secrets.
- Lets users choose guided dropdowns from the sidebar and edit the generated Cypher before running it.
- Generates editable Cypher from any combination of concentration, FLMB requirement, and foundation selections.
- Keeps a short in-session query history with graph node and relationship counts.
- Shows schema summaries for node labels, relationship types, and common label-to-label patterns.
- Shows a node color legend for courses, concentrations, FLMB requirements, foundations, suggested path nodes, and other nodes.
- Opens the Neo4j visual's node-properties panel by default so users can inspect selected nodes immediately.
- Highlights courses that satisfy more than one currently selected requirement.
- Sizes course nodes using independent 0-5 sidebar course-preference sliders for average recommendation and low workload.
- Greys out course nodes that have not been offered in selected terms within the selected lookback window.
- Lets users add visible courses to a plan and track progress against core degree requirements.
- Tracks concentration progress for planned courses using concentration eligibility counts.
- Provides sample queries for:
  - Finance and Entrepreneurship concentration courses plus prerequisites.
  - FLMB requirement relationships.
  - A limited "all relationships" graph.
- Includes a "Chart My Path" tab that:
  - Lets users choose concentrations.
  - Lets users mark courses already taken.
  - Builds a temporary ordered path of remaining candidate courses.
  - Renders that suggested path as a Neo4j visualization.

## Repository Layout

```text
.
├── README.md
├── requirements.txt
├── data/
│   ├── concentration_map.csv
│   ├── concentrations.csv
│   ├── courses.csv
│   ├── flmb_edges.csv
│   ├── flmb_entities.csv
│   ├── foundations_entities.csv
│   ├── foundations_map.csv
│   └── prereq_map.csv
├── pred/
│   ├── class_term_pred.csv
│   └── term_pred.py
└── ui/
    ├── app.py
    ├── path_gen.py
    └── Neo4j-eedbb37c-Created-2026-03-08.txt
```

## Main Components

### `ui/app.py`

The main Streamlit application.

Key responsibilities:

- Sets up the Streamlit page in wide mode.
- Creates a cached Neo4j driver from `st.secrets`.
- Loads concentration and course names from local CSV files.
- Defines sample Cypher queries.
- Renders an initial welcome screen.
- Implements the "Explore Classes" tab.
  - Separate dropdown controls for concentrations, FLMB requirements, and foundations build one combined graph query.
  - The generated Cypher box is collapsed by default and remains editable for advanced users.
  - Course preference sliders resize course nodes by average recommendation and low hours outside class without rerunning the graph query.
  - Term and lookback controls recolor courses based on `terms_offered` without rerunning the graph query.
  - Strategic Pick courses are highlighted when they meet more than one selected concentration, FLMB requirement, or foundation.
  - An "Add to Plan" control above the graph adds visible courses to the degree planner below.
  - A degree requirements planner below the graph tracks planned classes against foundations, FLMB categories, and electives.
  - A concentration progress tracker shows completed and in-progress concentrations based on planned eligible courses.
- Implements the "Chart My Path" tab.
- Uses `neo4j_viz` to convert Neo4j graph results into interactive HTML.
- Post-processes the generated `neo4j_viz` HTML so the visual's right-side node-properties panel starts open.

### `ui/path_gen.py`

Contains an alternate `generate_suggested_path` helper that performs a simple prerequisite-aware ordering of courses. This file is not currently imported by `ui/app.py`; the app has an inline path generator inside the "Chart My Path" tab.

### `pred/term_pred.py`

Builds a course offering probability table from `data/courses.csv`.

It parses each course's historical `terms_offered`, trains a basic logistic regression model when there is enough variation, and writes a future quarter probability grid to `pred/class_term_pred.csv`.

### `data/*.csv`

Local source data for courses, concentrations, foundations, prerequisites, and FLMB requirements. These files are read directly by the app and prediction script, and they also appear to describe the expected graph import shape.

## Neo4j Graph Shape

The application assumes the Neo4j database is already populated. There is no import or migration script in this repository right now.

The app queries these labels and properties:

- `Courses`
  - Expected properties include `course_name` and fields from `data/courses.csv`, such as `course_number`, `terms_offered`, workload metrics, and recommendation metrics.
- `concentration`
  - Expected property: `Concentration`.
- Other requirement-style nodes inferred from the data, such as foundations and FLMB entities.

The app uses or displays these relationship types:

- `INCLUDE`
  - Connects concentrations to course or requirement structures.
- `UNLOCKS`
  - Represents prerequisite unlocking relationships between courses.
- `flmb_requirement`
  - Represents FLMB requirement relationships.
- `NEXT`
  - Created temporarily by the "Chart My Path" workflow, then deleted immediately after rendering.

The default graph query is:

```cypher
MATCH path = (c:concentration)-[:INCLUDE*]->(p:Courses)
WHERE c.Concentration = "Finance" OR c.Concentration = "Entrepreneurship"
OPTIONAL MATCH prereqPath = (p)<-[:UNLOCKS*]-(pre:Courses)
RETURN path, prereqPath
```

## Data Files

| File | Purpose |
| --- | --- |
| `data/courses.csv` | Course catalog data, including course numbers, names, historical offering terms, workload, and recommendations. |
| `data/concentrations.csv` | List of concentration names shown in the path planner. |
| `data/concentration_map.csv` | Maps concentrations to course numbers. |
| `data/prereq_map.csv` | Maps courses to prerequisites. |
| `data/foundations_entities.csv` | Foundation requirement names. |
| `data/foundations_map.csv` | Maps foundations to course numbers and requirement types. |
| `data/flmb_entities.csv` | FLMB category or subtype names. |
| `data/flmb_edges.csv` | Maps FLMB requirement categories to courses. |
| `pred/class_term_pred.csv` | Generated future course offering probabilities. |

`data/degree_requirements` is intentionally ignored by git. It can exist locally as a private working note, but production behavior should rely on the structured CSV requirement maps and constants in `ui/app.py`.

## Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Streamlit secrets

Create `.streamlit/secrets.toml` in the repository root:

```toml
NEO4J_URI = "neo4j+s://your-instance.databases.neo4j.io"
NEO4J_USERNAME = "your-username"
NEO4J_PASSWORD = "your-password"
```

The app reads these values in `ui/app.py`:

```python
st.secrets["NEO4J_URI"]
st.secrets["NEO4J_USERNAME"]
st.secrets["NEO4J_PASSWORD"]
```

### 4. Make sure Neo4j is populated

Before running the app, load the graph database with nodes and relationships that match the expected labels, properties, and relationship types described above.

At minimum, the default UI expects:

- `(:concentration {Concentration: "Finance"})`
- `(:concentration {Concentration: "Entrepreneurship"})`
- `(:Courses {course_name: ...})`
- Concentration-to-course paths through `[:INCLUDE]`
- Course prerequisite paths through `[:UNLOCKS]`

## Run the App

```bash
streamlit run ui/app.py
```

Streamlit will print a local URL, usually `http://localhost:8501`.

## Regenerate Course Term Predictions

From the `pred/` directory:

```bash
cd pred
python term_pred.py
```

This rewrites `pred/class_term_pred.csv`.

Notes:

- `term_pred.py` expects `../data/courses.csv`.
- `data/courses.csv` must include `course_name` and `terms_offered`.
- `terms_offered` values should look like `Autumn 2021,Spring 2023,Spring 2025`.

## Current Limitations

- The repository does not include a Neo4j import script, so database setup must happen separately.
- The "Chart My Path" planner currently chooses candidate courses in database result order and limits the list to the requested maximum. It does not yet optimize for prerequisites, course availability probabilities, workload, quarter constraints, or concentration completion rules.
- `ui/path_gen.py` contains a prerequisite-aware planner helper, but the Streamlit app currently uses an inline generator instead.
- `pred/class_term_pred.csv` is loaded in the inline path planner, but the current planner does not use the probabilities to sort or schedule courses.
- The file `ui/Neo4j-eedbb37c-Created-2026-03-08.txt` appears to contain a Neo4j Aura connection export. Treat database credentials as sensitive and prefer `.streamlit/secrets.toml` or deployment-level secrets for local and production use.

## Development Notes

- Use `streamlit run ui/app.py` for manual testing.
- Keep query-returning graph visualizations in the form `RETURN n, r, m` or `RETURN path` so `result.graph()` has nodes and relationships to render.
- The app relies on `st.cache_resource` for the Neo4j driver and `st.cache_data` for local CSV lists.
- `neo4j_viz.from_neo4j()` is used for rendering. If graph rendering fails, first check whether the Cypher query returned graph objects rather than only scalar values.
- Node colors are assigned from `NODE_TYPE_COLORS` in `ui/app.py`; update the legend and color map together.
- Course node sizes are assigned in `render_graph_html()` from the current course-preference settings; non-course node sizes are left unchanged.
- Strategic Pick highlighting is based on the currently selected dropdown values, not every requirement in the full catalog.
- Term availability filtering parses course `terms_offered` values like `Autumn 2021`; empty term selection means no availability greying.
- The degree planner uses `data/foundations_map.csv`, `data/flmb_edges.csv`, `data/concentration_map.csv`, and the requirement thresholds in `ui/app.py`. The optional local `data/degree_requirements` note is ignored and not required for Streamlit deployment.
- The planner currently tracks 3 foundation categories, 7 of 8 FLMB categories, and 10 tagged electives.
- Concentration progress uses `data/concentration_map.csv` plus course-count thresholds from the degree requirements text. It does not yet audit detailed subcategory rules.
- Temporary path planner nodes use a generated label like `SuggestedCourse_ab12cd` and are deleted with `DETACH DELETE` after rendering.

## Suggested Next Improvements

- Add a graph import script for the CSV files.
- Move the inline path planner out of `ui/app.py` and reconcile it with `ui/path_gen.py`.
- Use `pred/class_term_pred.csv` to rank or schedule courses by likely quarter availability.
- Add prerequisite-aware path planning to the Streamlit workflow.
- Add tests for prediction table generation and path planning behavior.
- Remove committed database credential exports and document secure secret handling for deployment.
