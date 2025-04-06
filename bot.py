import csv
import requests
from bs4 import BeautifulSoup
import re
import json

def sanitize_for_regex(text):
    """Sanitizes text for use in regular expressions."""
    return re.escape(text)

def csv_to_google_form(csv_filepath, form_url, field_mappings):
    """Reads data from CSV, submits to Google Form, handles name combining."""
    try:
        form_response_url = form_url.replace('/viewform', '/formResponse')
        all_submissions_successful = True

        with open(csv_filepath, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                form_data = {}

                # --- Name Combining Logic ---
                if 'firstname' in field_mappings and 'lastname' in field_mappings:
                    # Separate firstname and lastname fields exist.  Fill normally.
                    for csv_column, form_entry_id in field_mappings.items():
                        form_data[form_entry_id] = row.get(csv_column, "")
                else:
                    # Check for a single name-related field.
                    single_name_field = None
                    for form_label, entry_id in entry_ids.items():  # Use entry_ids
                        if 'firstname' in mappings and mappings['firstname'] == entry_id:
                            single_name_field = entry_id
                            break  # Found the single name field (mapped to firstname).

                    if single_name_field:
                        # Combine firstname and lastname (if available).
                        firstname = row.get('firstname', '')
                        lastname = row.get('lastname', '')
                        combined_name = f"{firstname} {lastname}".strip()
                        form_data[single_name_field] = combined_name

                        # Fill other non-name fields.
                        for csv_column, form_entry_id in field_mappings.items():
                            if csv_column not in ('firstname', 'lastname'):
                                form_data[form_entry_id] = row.get(csv_column, "")
                    else:
                        # No name field found (or only lastname).  Fill all as usual.
                        for csv_column, form_entry_id in field_mappings.items():
                            form_data[form_entry_id] = row.get(csv_column, "")
                # --- End Name Combining Logic ---

                try:
                    response = requests.post(form_response_url, data=form_data)
                    response.raise_for_status()
                    print(f"Successfully submitted data for row: {row}")
                except requests.exceptions.RequestException as e:
                    print(f"Error submitting data for row {row}: {e}")
                    all_submissions_successful = False

        return all_submissions_successful

    except FileNotFoundError:
        print(f"Error: File not found: '{csv_filepath}'")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False


def get_form_entry_ids(form_url):
    """Extracts entry IDs and field labels from a Google Form."""
    try:
        response = requests.get(form_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        entry_ids = {}
        list_items = soup.find_all('div', role='listitem')

        for item in list_items:
            question_span = item.find('span')
            if not question_span:
                print("Warning: Could not find question span. Skipping.")
                continue
            question_text = question_span.text.strip()

            parent_div = item.find('div', {'data-params': True})
            if not parent_div:
                print(f"Warning: No parent div with data-params for '{question_text}'. Skipping.")
                continue

            data_params = parent_div.get('data-params')
            if not data_params:
                print(f"Warning: 'data-params' attribute empty for '{question_text}'. Skipping.")
                continue

            try:
                match = re.search(r'\[\[(\d+)', data_params)
                if match:
                    entry_id = "entry." + match.group(1)
                else:
                    print(f"Warning: Could not extract entry ID from data-params for '{question_text}'. Skipping.")
                    continue
            except (ValueError, IndexError) as e:
                print(f"Warning: Error parsing data-params for '{question_text}': {e}. Skipping.")
                continue
            entry_ids[question_text] = entry_id

        return entry_ids if entry_ids else None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching form HTML: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def find_matching_keys_with_regex(entry_id_dict, csv_header, regex_patterns_file):
    """Maps CSV column names to form field labels using regex from a JSON file."""
    try:
        with open(regex_patterns_file, 'r', encoding='utf-8') as f:
            regex_patterns = json.load(f)
    except FileNotFoundError:
        print(f"Error: Regex patterns file not found: '{regex_patterns_file}'")
        return {}
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in '{regex_patterns_file}'")
        return {}

    mappings = {}
    used_entry_ids = set()

    for csv_col in csv_header:
        best_match = None
        best_score = 0

        for form_label, entry_id in entry_id_dict.items():
            if entry_id in used_entry_ids:
                continue

            for pattern_data in regex_patterns.get(csv_col, []):
                pattern = pattern_data['pattern']
                score = pattern_data['score']
                match_type = pattern_data.get('match_type', 'contains')

                try:
                    if match_type == 'exact':
                      if re.search(r"^" + sanitize_for_regex(pattern) + r"$", form_label, re.IGNORECASE):
                          if score > best_score:
                              best_score = score
                              best_match = entry_id
                    elif match_type == 'contains':
                        if re.search(sanitize_for_regex(pattern), form_label, re.IGNORECASE):
                            if score > best_score:
                                best_score = score
                                best_match = entry_id
                    elif match_type == 'reverse_contains':
                        if re.search(sanitize_for_regex(form_label), pattern, re.IGNORECASE):
                            if score > best_score:
                                best_score = score
                                best_match = entry_id

                except re.error as e:
                    print(f"Warning: Invalid regex pattern '{pattern}' for CSV column '{csv_col}': {e}")
                    continue

        if best_match:
            mappings[csv_col] = best_match
            used_entry_ids.add(best_match)

    return mappings


def main():
    csv_filepath = "team.csv"
    form_url = "FORM_PLACEHOLDER" # Add your form URL here
    regex_patterns_file = "regex_patterns.json"

    print("\nAttempting to automatically extract form entry IDs...")
    global entry_ids
    entry_ids = get_form_entry_ids(form_url)

    if entry_ids:
        print("\nExtracted Form Entry IDs:")
        for label, entry_id in entry_ids.items():
            print(f"  {label}: {entry_id}")

        try:
            with open(csv_filepath, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                csv_header = next(reader)
        except FileNotFoundError:
            print(f"Error: CSV file not found at {csv_filepath}")
            return
        except Exception as e:
            print(f"Error opening CSV file: {e}")
            return

        print("\nCSV Header Columns:")
        for col in csv_header:
            print(f"  {col}")

        print("\nAttempting to automatically map CSV columns to form fields using Regex...")
        global mappings
        mappings = find_matching_keys_with_regex(entry_ids, csv_header, regex_patterns_file)

        if not mappings:
            print("\nNo mappings could be determined. Exiting.")
            return

        print("\nRegex Mappings:")
        for csv_col, entry_id in mappings.items():
            print(f"  {csv_col}: {entry_id}")

        print("\nSubmitting data to Google Form...")
        success = csv_to_google_form(csv_filepath, form_url, mappings)

        if success:
            print("\nAll data submitted successfully!")
        else:
            print("\nSome submissions failed. See error messages above.")

    else:
        print("\nAutomatic extraction failed. Exiting.")


if __name__ == "__main__":
    main()