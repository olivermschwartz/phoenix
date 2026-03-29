# generate_class_predictions_full.py

import pandas as pd
from sklearn.linear_model import LogisticRegression
import itertools

# --------------------------------------
# Configuration
# --------------------------------------
QUARTERS = ["winter", "spring", "summer", "autumn"]

QUARTER_MAP = {
    "winter": 1,
    "spring": 2,
    "summer": 3,
    "autumn": 4
}

# --------------------------------------
# Parse offerings string into DataFrame
# --------------------------------------
def parse_offerings(course, offering_string):
    rows = []
    entries = [x.strip() for x in offering_string.split(",") if x.strip()]
    for e in entries:
        q, y = e.split()
        rows.append({
            "course": course,
            "year": int(y),
            "quarter": q.lower(),
            "offered": 1
        })
    return pd.DataFrame(rows)

# --------------------------------------
# Expand missing quarters
# --------------------------------------
def expand_quarters(course_df):
    min_year = course_df.year.min()
    max_year = course_df.year.max()
    rows = []
    for year in range(min_year, max_year + 1):
        for q in QUARTERS:
            offered = ((course_df.year == year) & (course_df.quarter == q)).any()
            rows.append({
                "year": year,
                "quarter": q,
                "offered": int(offered)
            })
    df = pd.DataFrame(rows)
    df["quarter_num"] = df["quarter"].map(QUARTER_MAP)
    df["year_index"] = df["year"] - df["year"].min()
    return df

# --------------------------------------
# Generate future quarters
# --------------------------------------
def generate_future_quarters(start_year, start_quarter, n_quarters=10):
    q_index = QUARTERS.index(start_quarter)
    result = []
    year = start_year
    for i in range(n_quarters):
        q = QUARTERS[(q_index + i) % 4]
        if q == "winter" and i > 0:
            year += 1
        result.append((q, year))
    return result

# --------------------------------------
# Build predictions table (full grid)
# --------------------------------------
def build_offering_probability_table_full(df, start_year, start_quarter, n_quarters=10):
    predictions_list = []
    future_quarters = generate_future_quarters(start_year, start_quarter, n_quarters)
    
    for _, row in df.iterrows():
        course = row["course_name"]
        offering_string = row["terms_offered"]
        course_df = parse_offerings(course, offering_string)
        course_df = expand_quarters(course_df)
        
        X = course_df[["year_index", "quarter_num"]]
        y = course_df["offered"]
        base_year = course_df.year.min()
        
        # Train logistic regression if possible
        if y.nunique() < 2:
            base_probability = y.mean()  # fallback
        else:
            model = LogisticRegression()
            model.fit(X, y)
        
        # Build full rectangular table: all future quarters
        for q, year in future_quarters:
            year_idx = year - base_year
            quarter_num = QUARTER_MAP[q]
            if y.nunique() < 2:
                prob = base_probability
            else:
                predict_df = pd.DataFrame({"year_index":[year_idx], "quarter_num":[quarter_num]})
                prob = model.predict_proba(predict_df)[0][1]
            predictions_list.append({
                "course": course,
                "quarter": q,
                "year": year,
                "probability": prob
            })
    
    return pd.DataFrame(predictions_list)

# --------------------------------------
# Main execution
# --------------------------------------
if __name__ == "__main__":
    INPUT_CSV = "../data/courses.csv"   # Must have columns: course_name, terms_offered
    OUTPUT_CSV = "class_term_pred.csv"
    
    df = pd.read_csv(INPUT_CSV)
    
    predictions_table = build_offering_probability_table_full(
        df, start_year=2025, start_quarter="autumn", n_quarters=20
    )
    
    # Optional: sort by year, quarter, probability
    predictions_table = predictions_table.sort_values(["year","quarter","probability"], ascending=[True,True,False])
    
    predictions_table.to_csv(OUTPUT_CSV, index=False)
    print(f"Full predictions table saved to {OUTPUT_CSV}")