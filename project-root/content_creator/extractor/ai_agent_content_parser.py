from sqlalchemy.orm import Session
import fitz  # PyMuPDF
import spacy
import random
from collections import Counter
import logging
import requests

from .settings import get_setting, get_ollama_settings  # Correctly import get_setting
from .models import SessionLocal, Character

logger = logging.getLogger('app')

# Load spaCy model
nlp = spacy.load("en_core_web_sm")
nlp.max_length = 2000000

def generate_content(prompt: str, ollama_url: str, ollama_model: str) -> str:
    try:
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": ollama_model, "prompt": prompt, "stream": False}
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except Exception as e:
        print(f"Error generating content: {e}")
        return "Sorry, I couldn't process that request."

def extract_text_from_pdf(pdf_content):
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def extract_names(text):
    doc = nlp(text)
    names = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
    return names

def consolidate_names(names):
    # Frequency analysis
    name_counts = Counter(names)
    common_names = [name for name, count in name_counts.items() if count > 1]
    return common_names

def generate_character_details(name, ollama_url, ollama_model):
    prompt = f"Provide a detailed description for the character {name} including their name, sex, age, traits, behaviors, a brief background summary, and some dialogue examples in bullet points."
    details = generate_content(prompt, ollama_url, ollama_model)
    return details

def generate_book_details(text, db, ollama_url, ollama_model):
    prompt = f"Provide the book title, author, and genre of the following text: {text}"
    details = generate_content(prompt, ollama_url, ollama_model)
    details_dict = parse_character_details(details)  # Assuming the same function can parse book details
    return details_dict

def get_summary(text, db, ollama_url, ollama_model):
    prompt = f"Summarize the following story: {text}"
    summary = generate_content(prompt, ollama_url, ollama_model)
    return summary

def process_character_details(names, db: Session, book_details_dict, ollama_url: str, ollama_model: str):
    detailed_summaries = {}
    random_names = random.sample(names, min(5, len(names)))
    for i, name in enumerate(random_names, 1):
        logger.info(f"Agent checking character #{i}: {name}")
        summary = generate_character_details(name, ollama_url, ollama_model)
        if "I apologize" not in summary:
            details_dict = parse_character_details(summary)
            logger.info(f"Parsed Character Details: {details_dict}")
            if 'name' in details_dict and details_dict.get('name'):
                save_character_to_db(details_dict, db, book_details_dict)
                detailed_summaries[name] = details_dict
            else:
                logger.info(f"Character name is missing or invalid: {details_dict}")
    return detailed_summaries

def parse_character_details(details):
    details_dict = {}
    current_key = None
    current_value = []

    valid_keys = ["name", "sex", "age", "traits", "behaviors", "background", "dialogue examples"]

    for line in details.split('\n'):
        line = line.strip().replace('**', '')  # Remove asterisks
        if not line:
            continue
        key = line.split(':')[0].strip().lower()
        if ':' in line and key in valid_keys:
            if current_key and current_value:
                details_dict[current_key] = ' '.join(current_value).strip()
            current_key = key
            current_value = [line.split(':', 1)[1].strip()]
        else:
            current_value.append(line.strip())

    if current_key and current_value:
        details_dict[current_key] = ' '.join(current_value).strip()
    return details_dict

def save_character_to_db(details_dict, db, book_details_dict):
    if not db.query(Character).filter(Character.name == details_dict['name']).first():
        new_character = Character(
            name=details_dict.get('name'),
            sex=details_dict.get('sex', ''),
            age=details_dict.get('age', ''),
            traits=details_dict.get('traits', ''),
            behaviors=details_dict.get('behaviors', ''),
            background=details_dict.get('background', ''),
            book_title=book_details_dict.get('book title', ''),
            author=book_details_dict.get('author', ''),
            dialogue_examples=details_dict.get('dialogue examples', ''),
            genre=book_details_dict.get('genre', '')
        )
        db.add(new_character)
        db.commit()
        db.refresh(new_character)