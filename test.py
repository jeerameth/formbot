import csv
import requests
import urllib.parse
from bs4 import BeautifulSoup

def csv_to_google_form(csv_filepath, form_url, field_mappings):
    """
    Reads data from a local CSV file and submits it to a Google Form.
    Uses formResponse URL and POST request

    Args:
        csv_filepath: Path to the local CSV file.
        form_url: URL of the Google Form (the regular view URL).
        field_mappings: Dictionary mapping CSV column names to Google Form entry IDs.

    Returns:
        True if all submissions were successful, False otherwise.
    """
    try:
        # 1. Construct the formResponse URL
        form_response_url = form_url.replace('/viewform', '/formResponse')

        with open(csv_filepath, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            all_submissions_successful = True

            for row in reader:
                form_data = {}
                for csv_column, form_entry_id in field_mappings.items():
                    form_data[form_entry_id] = row.get(csv_column, "")

                # No need to URL-encode here; requests handles it for POST data.
                # encoded_data = urllib.parse.urlencode(form_data) # Removed

                try:
                    # 2. Use a POST request to the /formResponse URL
                    response = requests.post(form_response_url, data=form_data)
                    response.raise_for_status()  # Check for HTTP errors
                    print(f"Successfully submitted data for row: {row}")

                except requests.exceptions.RequestException as e:
                    print(f"Error submitting data for row {row}: {e}")
                    all_submissions_successful = False

            return all_submissions_successful

    except FileNotFoundError:
        print(f"Error: CSV file not found at '{csv_filepath}'")
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False


def get_form_entry_ids(form_url):
    """
    Extracts entry IDs and field labels from a Google Form using BeautifulSoup.
    """
    try:
        response = requests.get(form_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')
        entry_ids = {}

        list_items = soup.find_all('div', role='listitem')

        for item in list_items:
            question_span = item.find('span')
            if not question_span:
                print("Warning: Could not find question span within listitem. Skipping.")
                continue
            question_text = question_span.text.strip()

            parent_div = item.find('div', {'data-params': True})
            if not parent_div:
                print(f"Warning: Could not find parent div with data-params for question '{question_text}'. Skipping.")
                continue

            data_params = parent_div.get('data-params')
            if not data_params:
                print(f"Warning: 'data-params' attribute is empty for question '{question_text}'. Skipping.")
                continue

            try:
                import re
                match = re.search(r'\[\[(\d+)', data_params)
                if match:
                   entry_id = "entry." + match.group(1)
                else:
                     print(f"Warning: Could not extract entry ID from data-params for '{question_text}'. Skipping.")
                     continue
            except (ValueError, IndexError) as e:
                print(f"Warning: Error parsing data-params for question '{question_text}': {e}. Skipping.")
                continue
            entry_ids[question_text] = entry_id

        return entry_ids if entry_ids else None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching form HTML: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None



def find_matching_keys(entry_id_dict, csv_header):
    """
    Automatically maps CSV column names to form field labels (entry IDs).
    """
    mappings = {}
    used_entry_ids = set()

    for csv_col in csv_header:
        best_match = None
        best_match_score = 0

        for form_label, entry_id in entry_id_dict.items():
            if entry_id in used_entry_ids:
                continue

            if csv_col.lower() == form_label.lower():
                best_match = entry_id
                best_match_score = 100
                break

            score = 0
            if csv_col.lower() in form_label.lower():
                score += 50
            if form_label.lower() in csv_col.lower():
                score += 40
            score += max(0, 10 - abs(len(csv_col) - len(form_label)))

            if score > best_match_score:
                best_match_score = score
                best_match = entry_id

        if best_match:
            mappings[csv_col] = best_match
            used_entry_ids.add(best_match)
            print(f"Mapped CSV column '{csv_col}' to form field '{best_match}' (label: '{ [k for k, v in entry_id_dict.items() if v == best_match][0] }')")
        else:
            print(f"Warning: Could not automatically map CSV column '{csv_col}'. Skipping this column.")
            # Don't add to mappings if no match is found
    return mappings


def main():
    csv_filepath = "test2.csv"  # Replace with your CSV file
    form_url = "https://docs.google.com/forms/d/e/1FAIpQLSe-1isITQZCOh1hWQTlJ2dEDzRuqlxT9mU3kLiXAW4Z-EGziQ/viewform" # Replace

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
        field_mappings = find_matching_keys(entry_ids, csv_header)

        if not field_mappings:
            print("\nNo mappings could be determined.  Exiting.")
            return

        print("\nSubmitting data to Google Form...")
        success = csv_to_google_form(csv_filepath, form_url, field_mappings)

        if success:
            print("\nAll data submitted successfully!")
        else:
            print("\nSome submissions failed.  See error messages above.")

    else:
        print("\nAutomatic extraction failed.  Exiting.")


if __name__ == "__main__":
    main()