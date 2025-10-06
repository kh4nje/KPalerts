import streamlit as st
import pandas as pd
import numpy as np
import io

# Page config
st.set_page_config(page_title="Outbreak Alert System", layout="wide")

# Title
st.title("🩺 Outbreak Alert System")
st.markdown("Upload your weekly surveillance data (XLSX format) to generate alerts based on seasonal thresholds.")

# Load thresholds from GitHub (replace with your repo's raw URL once uploaded)
@st.cache_data
def load_thresholds(github_url):
    try:
        thresholds_df = pd.read_csv(github_url)
        return thresholds_df
    except Exception as e:
        st.error(f"Error loading thresholds: {e}")
        return None

# GitHub raw URL for thresholds CSV (update this after uploading to your repo)
THRESHOLDS_URL = "https://raw.githubusercontent.com/yourusername/yourrepo/main/seasonal_thresholds.csv"  # Replace with actual URL

# Load thresholds
thresholds = load_thresholds(THRESHOLDS_URL)
if thresholds is None:
    st.stop()

st.success(f"Thresholds loaded: {len(thresholds)} rows")

# Sidebar for params
st.sidebar.header("Alert Parameters")
min_deviation = st.sidebar.slider("Minimum Deviation (cases above threshold)", 1, 10, 3)
show_all = st.sidebar.checkbox("Show all data (including Normal)?", value=False)

# File uploader
uploaded_file = st.file_uploader("Upload Weekly Data (XLSX)", type="xlsx")

if uploaded_file is not None:
    # Read uploaded file
    current_df = pd.read_excel(uploaded_file)
    st.write("Uploaded data shape:", current_df.shape)
    
    # Process Facility_ID
    org_cols = ['orgunitlevel1', 'orgunitlevel2', 'orgunitlevel3', 'orgunitlevel4', 'orgunitlevel5', 'orgunitlevel6', 'organisationunitname']
    for col in org_cols:
        if col in current_df.columns:
            current_df[col] = current_df[col].fillna('Unknown').astype(str)
    current_df['Facility_ID'] = (current_df['orgunitlevel1'] + '_' + current_df['orgunitlevel2'] + '_' + 
                                 current_df['orgunitlevel3'] + '_' + current_df['orgunitlevel4'] + '_' + 
                                 current_df['orgunitlevel5'] + '_' + current_df['orgunitlevel6'] + '_' + 
                                 current_df['organisationunitname'])
    
    # Parse periodname
    current_df['periodname'] = current_df['periodname'].astype(str).str.strip()
    patterns = [r'Week (\d+) (\d{4})-\d{2}-\d{2} - \d{4}-\d{2}-\d{2}']
    extracted = current_df['periodname'].str.extract(patterns[0])
    extracted.columns = ['Week', 'Year']
    current_df = pd.concat([current_df, extracted], axis=1)
    current_df['Year'] = pd.to_numeric(current_df['Year'], errors='coerce')
    current_df['Week'] = pd.to_numeric(current_df['Week'], errors='coerce')
    current_df = current_df.dropna(subset=['Year', 'Week'])
    
    # Disease cols
    disease_cols = [col for col in current_df.columns if '(New Cases)' in col or '(New cases)' in col]
    current_df[disease_cols] = current_df[disease_cols].fillna(0)
    current_df[disease_cols] = current_df[disease_cols].astype(int)
    
    # Assign season
    def assign_season(week):
        if pd.isna(week):
            return 'Unknown'
        week = int(week)
        if 10 <= week <= 20:
            return 'Spring'
        elif 21 <= week <= 35:
            return 'Summer'
        elif 36 <= week <= 43:
            return 'Autumn'
        else:
            return 'Winter'
    
    current_df['Season'] = current_df['Week'].apply(assign_season)
    
    # Melt
    current_long = pd.melt(current_df, id_vars=['Facility_ID', 'Season'], 
                           value_vars=disease_cols, 
                           var_name='Disease', value_name='Cases')
    current_long['Cases'] = pd.to_numeric(current_long['Cases'], errors='coerce')
    
    # Override for year-round
    year_round_diseases = [
        'Acute Flaccid Paralysis (New Cases)', 'Botulism (New Cases)', 'Gonorrhea (New Cases)', 
        'HIV/AIDS (New Cases)', 'Leprosy (New Cases)', 'Nosocomial Infections (New Cases)', 
        'Syphilis (New Cases)', 'Visceral Leishmaniasis (New Cases)', 'Neonatal Tetanus (New Cases)'
    ]
    current_long.loc[current_long['Disease'].isin(year_round_diseases), 'Season'] = 'Year-Round'
    
    # Merge with thresholds
    alerts = current_long.merge(thresholds, on=['Facility_ID', 'Disease', 'Season'], how='left')
    alerts['Alert_Level'] = np.where(
        (alerts['Cases'] > alerts['Threshold_99']) & alerts['Threshold_99'].notna(), 'High Alert',
        np.where(
            (alerts['Cases'] > alerts['Threshold_95']) & alerts['Threshold_95'].notna(), 'Alert', 'Normal'
        )
    )
    # Deviation
    alerts['Deviation'] = np.where(
        alerts['Alert_Level'] == 'High Alert', alerts['Cases'] - alerts['Threshold_99'],
        np.where(alerts['Alert_Level'] == 'Alert', alerts['Cases'] - alerts['Threshold_95'], 0)
    )
    
    # Filter
    filtered_alerts = alerts[(alerts['Alert_Level'] != 'Normal') & alerts['Threshold_95'].notna() & (alerts['Deviation'] >= min_deviation)].copy()
    filtered_alerts = filtered_alerts[['Facility_ID', 'Disease', 'Season', 'Cases', 'Mean', 'SD', 'Threshold_95', 'Threshold_99', 'Alert_Level', 'Deviation']]
    
    # If show_all, include all merged (with Alert_Level)
    if show_all:
        all_data = alerts[['Facility_ID', 'Disease', 'Season', 'Cases', 'Mean', 'SD', 'Threshold_95', 'Threshold_99', 'Alert_Level', 'Deviation']].copy()
        all_data = all_data[all_data['Threshold_95'].notna()]  # Only where thresholds exist
        st.subheader("Full Data (Including Normal)")
        st.dataframe(all_data, use_container_width=True)
        csv = all_data.to_csv(index=False).encode('utf-8')
        st.download_button("Download Full Data CSV", csv, "full_data.csv", "text/csv")
    else:
        if not filtered_alerts.empty:
            st.subheader(f"Alerts Generated ({len(filtered_alerts)} total, min deviation: {min_deviation})")
            col1, col2 = st.columns(2)
            with col1:
                high_count = len(filtered_alerts[filtered_alerts['Alert_Level']=='High Alert'])
                st.metric("High Alerts", high_count)
            with col2:
                alert_count = len(filtered_alerts[filtered_alerts['Alert_Level']=='Alert'])
                st.metric("Moderate Alerts", alert_count)
            st.dataframe(filtered_alerts, use_container_width=True)
            csv = filtered_alerts.to_csv(index=False).encode('utf-8')
            st.download_button("Download Alerts CSV", csv, "current_alerts.csv", "text/csv")
        else:
            st.success("No alerts triggered this week—all within thresholds!")
else:
    st.info("Please upload your weekly data file to proceed.")
