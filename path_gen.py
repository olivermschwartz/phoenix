import streamlit as st

def generate_suggested_path(concentrations=None, selected_courses=None, driver=None):
    st.write(concentrations)
    if len(concentrations) == 0 or concentrations is None or "":
        st.write("Select at least one concentration, or use the 'Explore Classes' tab to explore all classes and relationships.")
        return None
    else: 
        st.write("Generating suggested path...this functionality is not yet implemented.")
        return None