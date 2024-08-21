import base64
from io import BytesIO
from PIL import Image
import streamlit as st
from lida import Manager, TextGenerationConfig, llm
from dotenv import load_dotenv
import os
import openai
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Load environment variables
load_dotenv()

# OpenAI API key
openai.api_key = os.getenv('OPENAI_API_KEY')
if openai.api_key is None:
    raise ValueError("OpenAI API key is not set.")

# Airtable environment variables
BASE_ID = os.getenv('AIRTABLE_BASE_ID')
SUMMARIES_TABLE_NAME = os.getenv('AIRTABLE_SUMMARIES_TABLE_NAME')
VISUALIZATIONS_TABLE_NAME = os.getenv('AIRTABLE_VISUALIZATIONS_TABLE_NAME')
AIRTABLE_PAT = os.getenv('AIRTABLE_PAT')

if not all([BASE_ID, SUMMARIES_TABLE_NAME, VISUALIZATIONS_TABLE_NAME, AIRTABLE_PAT]):
    raise ValueError("Airtable credentials are not set.")

# Google Drive API setup
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_FILE = 'https://github.com/ninjaksahni/infera/blob/37fde489e48d10cc1f2fc9f17767052079e87d7e/infera1-49e3d49a0ee5.json'

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# Initialize LIDA Manager
lida = Manager(text_gen=llm("openai"))
textgen_config = TextGenerationConfig(n=1, temperature=0.5, model="gpt-3.5-turbo", use_cache=True)

def base64_to_image(base64_string):
    """Convert a base64 string to a PIL Image."""
    byte_data = base64.b64decode(base64_string)
    return Image.open(BytesIO(byte_data))

def upload_image_to_drive(image: Image) -> str:
    """Upload image to Google Drive and return the file URL."""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    
    file_metadata = {
        'name': 'visualization.png',
        'mimeType': 'image/png'
    }
    media = MediaIoBaseUpload(buffer, mimetype='image/png')

    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()

    return file.get('webViewLink')

def save_to_airtable_summaries(summary):
    """Save summary to Airtable."""
    headers = {
        'Authorization': f'Bearer {AIRTABLE_PAT}',
        'Content-Type': 'application/json'
    }
    
    # Ensure summary is a plain text string
    if isinstance(summary, dict):
        summary = str(summary)  # Convert dict to string if necessary

    data = {
        'fields': {
            'Summary Text': summary  # Correct field name for summary
        }
    }
    
    response = requests.post(
        f'https://api.airtable.com/v0/{BASE_ID}/{SUMMARIES_TABLE_NAME}',
        headers=headers,
        json=data
    )
    
    if response.status_code != 200:
        st.error(f"Failed to save summary to Airtable: {response.json()}")
        return response.json()
    
    return response.json()

def save_to_airtable_visualizations(image_url):
    """Save visualization to Airtable."""
    headers = {
        'Authorization': f'Bearer {AIRTABLE_PAT}',
        'Content-Type': 'application/json'
    }
    
    # Ensure image_url is properly formatted
    if not isinstance(image_url, str):
        image_url = str(image_url)  # Convert to string if necessary
    
    data = {
        'fields': {
            'Image Link': image_url  # Use plain URL for Single Line Text field
        }
    }
    
    response = requests.post(
        f'https://api.airtable.com/v0/{BASE_ID}/{VISUALIZATIONS_TABLE_NAME}',
        headers=headers,
        json=data
    )
    
    if response.status_code != 200:
        st.error(f"Failed to save visualization to Airtable: {response.json()}")
        return response.json()
    
    return response.json()

# Initialize session state for CSV file path, summary, and graphs
if 'csv_file_path' not in st.session_state:
    st.session_state.csv_file_path = None

if 'summary' not in st.session_state:
    st.session_state.summary = None

if 'generated_charts' not in st.session_state:
    st.session_state.generated_charts = []

if 'chart_names' not in st.session_state:
    st.session_state.chart_names = []

# Sidebar menu
menu = st.sidebar.selectbox("Choose an Option", ["Summarize", "Question based Graph"])

# Display links to generated graphs with thumbnails
if st.session_state.generated_charts:
    st.sidebar.subheader("Generated Graphs")
    for name, img in zip(st.session_state.chart_names, st.session_state.generated_charts):
        # Save image to temporary file
        temp_file_path = "/tmp/temp_image.png"
        img.save(temp_file_path)

        # Create a base64 image string for thumbnail
        with open(temp_file_path, "rb") as file:
            img_base64 = base64.b64encode(file.read()).decode('utf-8')
            img_data = f"data:image/png;base64,{img_base64}"

        # Create HTML to show thumbnail and link
        html = f'''
        <a href="{img_data}" target="_blank">
            <img src="{img_data}" width="100" style="margin: 5px;" />
            {name}
        </a>
        '''
        st.sidebar.markdown(html, unsafe_allow_html=True)

if menu == "Summarize":
    st.header("📊 INFERA ONE 📊")
    st.subheader("Summarization of your Data")
    file_uploader = st.file_uploader("Upload your CSV", type="csv")
    if file_uploader is not None:
        st.session_state.csv_file_path = "filename.csv"
        with open(st.session_state.csv_file_path, "wb") as f:
            f.write(file_uploader.getvalue())
        
        # Summarize the CSV file
        summary = lida.summarize(st.session_state.csv_file_path, summary_method="default", textgen_config=textgen_config)
        st.write(summary)
        
        # Save summary to Airtable
        try:
            result = save_to_airtable_summaries(summary)
            if result:
                st.success("Summary saved to Airtable successfully!")
        except Exception as e:
            st.error(f"Error saving summary to Airtable: {e}")
        
        # Generate goals from the summary
        goals = lida.goals(summary, n=2, textgen_config=textgen_config)
        for goal in goals:
            st.write(goal)
        
        # Generate and display visualizations
        i = 0
        library = "seaborn"
        textgen_config = TextGenerationConfig(n=1, temperature=0.2, use_cache=True)
        
        # Ensure summary is properly handled
        if isinstance(summary, dict):
            summary_text = str(summary)  # Convert dict to string if necessary
        else:
            summary_text = summary
        
        charts = lida.visualize(summary=summary_text, goal=goals[i], textgen_config=textgen_config, library=library)  
        img_base64_string = charts[0].raster
        img = base64_to_image(img_base64_string)
        
        # Upload image and get URL
        try:
            image_url = upload_image_to_drive(img)
            st.image(img)
            result = save_to_airtable_visualizations(image_url)
            if result:
                st.success("Visualization saved to Airtable successfully!")
                # Add image URL and name to session state
                st.session_state.generated_charts.append(img)
                st.session_state.chart_names.append("Summary Chart")
        except Exception as e:
            st.error(f"Error saving visualization to Airtable: {e}")

elif menu == "Question based Graph":
    st.subheader("Query your Data to Generate Graph")
    if st.session_state.csv_file_path:
        text_area = st.text_area("Enter your query about the data:", height=200)
        if st.button("Generate Graph"):
            if len(text_area) > 0:
                st.info("Your Query: " + text_area)
                
                # Reinitialize LIDA Manager for new query
                textgen_config = TextGenerationConfig(n=1, temperature=0.2, use_cache=True)
                
                # Summarize the CSV file
                summary = lida.summarize(st.session_state.csv_file_path, summary_method="default", textgen_config=textgen_config)
                
                # Ensure summary is properly handled
                if isinstance(summary, dict):
                    summary_text = str(summary)  # Convert dict to string if necessary
                else:
                    summary_text = summary
                
                # Generate visualization based on user query
                user_query = text_area
                charts = lida.visualize(summary=summary_text, goal=user_query, textgen_config=textgen_config)  
                img_base64_string = charts[0].raster
                img = base64_to_image(img_base64_string)
                
                # Display the image directly
                st.image(img)
                
                # Upload image and get URL
                try:
                    image_url = upload_image_to_drive(img)
                    result = save_to_airtable_visualizations(image_url)
                    if result:
                        st.success("Visualization saved to Airtable successfully!")
                        # Add image URL and name to session state
                        st.session_state.generated_charts.append(img)
                        st.session_state.chart_names.append(user_query)
                except Exception as e:
                    st.error(f"Error saving visualization to Airtable: {e}")
    else:
        st.warning("Please upload a CSV file first.")
