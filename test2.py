import csv
import requests
from bs4 import BeautifulSoup
import browser_cookie3
import json
import google.generativeai as genai
import os
from dotenv import load_dotenv
import time
import re

load_dotenv()

def get_google_cookies(browser_name="chrome", cookies=None):
    """Retrieves Google cookies from browser or uses provided cookies."""
    if cookies:
        cj = requests.cookies.RequestsCookieJar()
        for cookie_data in cookies:
            expires = cookie_data.get('expirationDate')
            if expires is not None:
                expires = int(expires)
            domain = cookie_data.get('domain', '')
            path = cookie_data.get('path', '/')
            secure = cookie_data.get('secure', False)
            http_only = cookie_data.get('httpOnly', False)
            rest = {'HttpOnly': ''} if http_only else {}

            cookie = requests.cookies.create_cookie(
                domain=domain,
                name=cookie_data['name'],
                value=cookie_data['value'],
                expires=expires,
                path=path,
                secure=secure,
                rest=rest,
            )
            cj.set_cookie(cookie)
        print(f"Loaded provided cookies.")
        return cj

    try:
        load_function = getattr(browser_cookie3, browser_name)
        cj = load_function(domain_name='google.com')
        if any(cookie.name.startswith('S') and 'SID' in cookie.name for cookie in cj):
            print(f"Found Google sign-in cookies in {browser_name}.")
            return cj
        else:
            print(f"Warning: No Google sign-in cookies found in {browser_name}.")
            return None
    except Exception as e:
        print(f"Error loading cookies from {browser_name}: {e}")
        return None

def sanitize_for_prompt(text):
    """Removes or replaces characters that might cause issues."""
    text = text.replace('\n', ' ').replace('\t', ' ')
    text = re.sub(r'[^\w\s.,;:\-!?"]', '', text)
    return text

def csv_to_google_form(csv_filepath, form_url, field_mappings, user_credentials_file):
    """Reads data from CSV, submits to Google Form, handles multiple users."""
    try:
        form_response_url = form_url.replace('/viewform', '/formResponse')

        with open(user_credentials_file, 'r') as f:
            user_credentials = json.load(f)

        all_submissions_successful = True

        with open(csv_filepath, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                user_id = row.get('User', 'default')

                if user_id not in user_credentials:
                    print(f"Warning: User '{user_id}' not found. Skipping.")
                    all_submissions_successful = False
                    continue

                user_info = user_credentials[user_id]
                browser_name = user_info.get('browser', 'chrome')
                cookies = user_info.get('cookies')
                cj = get_google_cookies(browser_name, cookies)

                if not cj:
                    print(f"Warning: Could not load cookies for '{user_id}'. Skipping.")
                    all_submissions_successful = False
                    continue

                form_data = {}
                for csv_column, form_entry_id in field_mappings.items():
                    if csv_column != 'User':
                        if isinstance(form_entry_id, tuple):
                            form_data[form_entry_id[0]] = form_entry_id[1]
                        else:
                            form_data[form_entry_id] = row.get(csv_column, "")

                print(f"Form data being sent: {form_data}")
                session = requests.Session()
                session.cookies.update(cj)

                try:
                    response = session.post(form_response_url, data=form_data)
                    response.raise_for_status()
                    print(f"Successfully submitted data for row: {row} (User: {user_id})")
                except requests.exceptions.RequestException as e:
                    print(f"Error submitting data for row {row} (User: {user_id}): {e}")
                    if response.status_code == 302:
                        print("  (Sign-in issue.)")
                    all_submissions_successful = False

        return all_submissions_successful

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: {type(e).__name__} - {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

def get_form_entry_ids(form_url):
    """Extracts ALL entry IDs and labels, robustly handling different structures."""
    try:
        response = requests.get(form_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        entry_ids = {}

        # --- Robust Field Extraction ---
        containers = soup.find_all('div', {'data-params': True})
        for container in containers:
            input_field = container.find('input')
            textarea_field = container.find('textarea')

            if input_field:
                field_name = input_field.get('name')
                if field_name and field_name.startswith("entry."):
                    # --- Robust Label Extraction ---
                    label = _extract_label(container) or field_name
                    entry_ids[label] = field_name

            if textarea_field:
                field_name = textarea_field.get('name')
                if field_name and field_name.startswith("entry."):
                    label = _extract_label(container) or field_name
                    entry_ids[label] = field_name
        # ---

        # --- Hidden Field Extraction (Corrected) ---
        hidden_inputs = soup.find_all('input', type='hidden')
        for hidden_input in hidden_inputs:
            name = hidden_input.get('name')
            if name:
                value = hidden_input.get('value', '')
                entry_ids[name] = (name, value)
                print(f"Found hidden input field: {name}, Default Value: {value}")
        # ---

        return entry_ids

    except requests.exceptions.RequestException as e:
        print(f"Error fetching form HTML: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

def _extract_label(container):
    """Helper function to extract field labels robustly."""
    # Try to get label from aria-labelledby
    input_field = container.find('input')
    if input_field:
        aria_labelledby = input_field.get('aria-labelledby')
        if aria_labelledby:
            label_element = container.find(id=aria_labelledby)
            if label_element:
                return label_element.text.strip()
    #Try to get label from span
    question_span = container.find('span')
    if question_span:
       return question_span.text.strip()

    # Try to get label from surrounding div (works for some forms)
    label_div = container.find('div', role='heading')
    if label_div:
        return label_div.text.strip()



    return None  # No label found

def find_matching_keys_with_gemini(entry_id_dict, csv_header, api_key):
    """Uses Gemini to map CSV columns to form fields, EXCLUDING hidden."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash-lite')  # Use gemini-pro

    mappings = {}
    used_entry_ids = set()

    prompt_template = """You are a helpful assistant that maps CSV column names to Google Form entry IDs.
I will give you a list of CSV column names and a list of Google Form field labels with their corresponding entry IDs.
Your task is to determine the best mapping between the CSV columns and the *visible* form fields.
Return the mappings in a JSON format, where the keys are the CSV column names and the values are the corresponding entry IDs.
If no suitable mapping can be found for a CSV column, do NOT include it in the JSON output. Do not make up an entry ID.  Do *NOT* map any hidden fields.

CSV Columns:
{csv_columns}

Form Fields:
{form_fields}

JSON Mapping:
"""
    # --- Filter out hidden fields (tuples) BEFORE sending to Gemini ---
    filtered_entry_ids = {
        label: entry_id
        for label, entry_id in entry_id_dict.items()
        if isinstance(entry_id, str) and entry_id.startswith("entry.")
    }
    # ---

    sanitized_csv_columns = [sanitize_for_prompt(col) for col in csv_header]
    sanitized_form_fields = {sanitize_for_prompt(label): entry_id for label, entry_id in filtered_entry_ids.items()}

    csv_columns_str = "\n".join([f"- {col}" for col in sanitized_csv_columns])
    form_fields_str = "\n".join([f"- {label}: {entry_id}" for label, entry_id in sanitized_form_fields.items()])
    prompt = prompt_template.format(csv_columns=csv_columns_str, form_fields=form_fields_str)

    print(f"Prompt sent to Gemini:\n{prompt}")

    try:
        response = model.generate_content(prompt)
        time.sleep(1)
        print(f"Prompt feedback: {response.prompt_feedback}")
        print(f"Raw Gemini response: {response.text}")

        match = re.search(r"`(?:json)?\s*(\{[\s\S]*?\})\s*`", response.text, re.IGNORECASE)
        if match:
            json_string = match.group(1).strip()
            print(f"Extracted JSON string: {json_string}")
            try:
                mappings = json.loads(json_string)
            except json.JSONDecodeError as e:
                print(f"JSON Decode Error: {e}")
                return {}
        else:
            print("Error: Could not find JSON block in Gemini response.")
            return {}

        for csv_col, entry_id in mappings.items():
            if not isinstance(entry_id, str) or not entry_id.startswith("entry."):
                print(f"Warning: Invalid entry ID '{entry_id}' for CSV column '{csv_col}'.")
                continue
            if entry_id in used_entry_ids:
                print(f"Warning: entry ID '{entry_id}' already used. Skipping.")
                continue
            used_entry_ids.add(entry_id)

    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return {}

    # --- Add hidden fields BACK to the mappings, after Gemini ---
    for label, entry_id in entry_id_dict.items():
        if isinstance(entry_id, tuple):  # Hidden field (name, value)
            mappings[entry_id[0]] = entry_id  # Add hidden field
    # ---

    return mappings



def main():
    csv_filepath = "test2.csv"
    form_url = "https://docs.google.com/forms/d/e/1FAIpQLSe-1isITQZCOh1hWQTlJ2dEDzRuqlxT9mU3kLiXAW4Z-EGziQ/viewform"
    user_credentials_file = "user_credentials.json"
    gemini_api_key = os.environ.get("GEMINI_API_KEY")

    if gemini_api_key is None:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    print("\nAttempting to automatically extract form entry IDs...")
    entry_ids = get_form_entry_ids(form_url)

    if entry_ids:
        print("\nExtracted Form Entry IDs:")
        for label, entry_id in entry_ids.items():
            print(f"  {label}: {entry_id}")

        try:
            with open(csv_filepath, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                csv_header = next(reader)
                if 'User' not in csv_header:
                    print("Warning: 'User' column not found. Treating all as default.")
        except FileNotFoundError:
            print(f"Error: CSV file not found at {csv_filepath}")
            return
        except Exception as e:
            print(f"Error opening CSV file: {e}")
            return

        print("\nCSV Header Columns:")
        for col in csv_header:
            print(f"  {col}")

        print("\nAttempting to automatically map CSV columns to form fields...")
        filtered_header = [col for col in csv_header if col != 'User']
        field_mappings = find_matching_keys_with_gemini(entry_ids, filtered_header, gemini_api_key)

        if not field_mappings:
            print("\nNo mappings could be determined. Exiting.")
            return

        print("\nField Mappings:")
        for csv_col, entry_id in field_mappings.items():
            print(f"  {csv_col}: {entry_id}")

        print("\nSubmitting data to Google Form...")
        success = csv_to_google_form(csv_filepath, form_url, field_mappings, user_credentials_file)

        if success:
            print("\nAll data submitted successfully!")
        else:
            print("\nSome submissions failed. See error messages above.")
    else:
        print("\nAutomatic extraction failed. Exiting.")


if __name__ == "__main__":
    main()