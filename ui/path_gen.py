# path_gen.py
import pandas as pd

def generate_suggested_path(concentrations, selected_courses, driver, n_quarters=10):
    """
    Generate a suggested course path for a student.
    
    Parameters
    ----------
    concentrations : list[str]
        List of selected concentration names.
    selected_courses : list[str]
        List of course names already completed.
    driver : neo4j.Driver
        Neo4j driver connection.
    n_quarters : int
        Number of future quarters to plan.
    
    Returns
    -------
    List[dict]
        Ordered list of course nodes with info:
        {"course_name", "quarter", "year", "already_taken"}
    """

    if not concentrations:
        return []

    # --- Fetch all courses for selected concentrations ---
    query = f"""
    MATCH (c:concentration)-[:INCLUDE*]->(course:Courses)
    WHERE c.Concentration IN {concentrations}
    OPTIONAL MATCH prereqPath = (course)<-[:UNLOCKS*]-(pre:Courses)
    RETURN DISTINCT course.course_name AS course_name, collect(pre.course_name) AS prerequisites
    """

    with driver.session() as session:
        results = session.run(query)
        courses = []
        for record in results:
            courses.append({
                "course_name": record["course_name"],
                "prerequisites": record["prerequisites"]
            })

    # --- Remove duplicates and courses already taken from the candidate pool ---
    course_pool = {c["course_name"]: c for c in courses}

    # --- Build a simple topological order respecting prerequisites ---
    planned_courses = []
    taken_courses = set(selected_courses)
    remaining_courses = set(course_pool.keys())
    quarter_names = ["winter", "spring", "summer", "autumn"]
    year_counter = 0
    quarter_index = 0

    while remaining_courses and len(planned_courses) < n_quarters * 3:  # limit path length
        progress = False
        for course_name in list(remaining_courses):
            prereqs = set(course_pool[course_name]["prerequisites"])
            if prereqs.issubset(taken_courses):
                # Schedule this course
                planned_courses.append({
                    "course_name": course_name,
                    "quarter": quarter_names[quarter_index % 4],
                    "year": year_counter,
                    "already_taken": course_name in taken_courses
                })
                taken_courses.add(course_name)
                remaining_courses.remove(course_name)
                progress = True

                # Update quarter/year
                quarter_index += 1
                if quarter_index % 4 == 0:
                    year_counter += 1

                break  # schedule one course per iteration for simplicity

        if not progress:
            # Cannot schedule any remaining courses due to unsatisfied prerequisites
            break

    return planned_courses